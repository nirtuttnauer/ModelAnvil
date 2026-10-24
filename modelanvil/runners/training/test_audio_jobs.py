"""Small durable/media trust tests; actual TTS quality is qualified separately."""
import io
import uuid
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase
from modelanvil.api.views.audio import GenerateInput
from modelanvil.runners import audio_generation as audio
from modelanvil.runners.training import audio_runtime as runtime
from modelanvil.runners.training import test_hf_runtime as fixtures
from modelanvil.jobs.models import Job,WorkerPool
from modelanvil.budgets.models import BudgetPolicy,BudgetReservation
from modelanvil.runners.models import InferenceRequest,Model,ModelVersion,TokenizerVersion


class AudioContractTests(SimpleTestCase):
    def test_fixed_cpu_head_and_strict_generation_schema(self):
        self.assertEqual(runtime.CONTRACT['recipes'],['tts_output_head'])
        self.assertEqual(runtime.CONTRACT['trainable_parameters'],124578)
        self.assertEqual(runtime.runner_manifest()['resources']['gpu_count'],0)
        for kwargs in ({'recipe_type':'full_sft'},{'precision':'bf16'},{'adapter':'lora'},{'quantization':'4bit'}):
            with self.assertRaises(ValueError):runtime.validate_options(**kwargs)
        value={'model':str(uuid.uuid4()),'text':'Hello.','pool':1,'budget_policy':str(uuid.uuid4()),'idempotency_key':'same'}
        self.assertTrue(GenerateInput(data=value).is_valid())
        for update in ({'max_seconds':7},{'seed':-1},{'text':'x'*97},{'executor':'arbitrary'},{'text':' '}):
            self.assertFalse(GenerateInput(data={**value,**update}).is_valid())
        for args in [('hello',True,6),('hello',42,True),('hello',42,7),('',42,6)]:
            with self.assertRaises(ValueError):audio.controls(*args)

    def test_only_pinned_safe_conversion_is_admitted_before_deserialization(self):
        import tempfile
        from pathlib import Path
        from scripts.convert_speecht5 import convert
        try:import torch
        except ImportError:self.skipTest('Optional audio dependency is not installed.')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pytorch_model.bin';path.write_bytes(b'not a publisher checkpoint')
            with patch.object(torch,'load') as load:
                with self.assertRaisesRegex(ValueError,'checksum'):convert(path,Path(tmp)/'model.safetensors','tts')
                load.assert_not_called()


class AudioDurabilityTests(TestCase):
    setUp=fixtures.GPUInputTests.setUp
    store=fixtures.GPUInputTests.store

    def request(self,charges=None):
        tok=TokenizerVersion.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='audio-tokenizer')
        model=Model.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='audio-model')
        version=ModelVersion.all_objects.create(tenant_id=self.tenant.pk,project=self.project,model=model,tokenizer=tok,architecture_ref=runtime.RUNTIME_ID)
        pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='audio-pool')
        job=Job.all_objects.create(tenant_id=self.tenant.pk,project=self.project,pool=pool,name='audio')
        frozen={'settings':{'text':'Hello.','seed':42,'max_seconds':6}}
        record=InferenceRequest.all_objects.create(tenant_id=self.tenant.pk,project=self.project,principal_id='fixture',model_version=version,
            input_digest=audio.digest(frozen),status='running',configuration={'kind':audio.TYPE,'job_id':str(job.job_id),'frozen':frozen,'attempt_charges':charges or {}})
        job.payload={'type':audio.TYPE,'request_id':str(record.request_id),'input_digest':record.input_digest};job.save()
        policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='audio-quota',unit=audio.UNIT,period='lifetime',limit_amount=288000)
        reservation=BudgetReservation.reserve(tenant_id=self.tenant.pk,policy=policy,job_id=job.job_id,estimated_amount=288000)
        return job,record,reservation

    def test_fake_worker_success_without_wave_is_failure_and_accounts_unknown_compute(self):
        job,record,reservation=self.request({'attempt-1':{'samples':96000,'basis':'unknown_inflight_upper_bound'}})
        with patch.object(audio,'current_inputs'),patch.object(audio,'candidate_bundle',return_value={}):
            record.configuration['frozen']['plan']={};record.input_digest=audio.digest(record.configuration['frozen']);record.save()
            job.payload['input_digest']=record.input_digest;job.save()
            self.assertEqual(audio.finalize_job(job,'succeeded'),'failed')
        record.refresh_from_db();reservation.refresh_from_db()
        self.assertEqual(record.status,'failed');self.assertIsNone(record.usage)
        self.assertEqual(reservation.settled_amount,96000)
        self.assertEqual(reservation.usage_events.get().detail['basis'],'unknown_inflight_upper_bound')

    def test_requeued_attempt_keeps_reservation_and_cancel_settles_once(self):
        job,record,reservation=self.request()
        self.assertEqual(audio.finalize_job(job,'queued'),'queued');reservation.refresh_from_db();self.assertEqual(reservation.state,'reserved')
        audio.cancel(record);reservation.refresh_from_db();self.assertEqual(reservation.settled_amount,0)
        self.assertEqual(reservation.state,'settled');record.refresh_from_db();self.assertEqual(record.status,'cancelled')
        with self.assertRaises(ValueError):audio.cancel(record)

    def test_metadata_only_candidate_and_wrong_project_refused_before_load(self):
        job,record,_=self.request()
        with patch.object(runtime.math,'load_model') as load:
            with self.assertRaises(ValueError):audio.candidate_bundle(record.model_version,self.tenant.pk,self.project.pk)
            with self.assertRaises(ValueError):audio.candidate_bundle(record.model_version,self.tenant.pk,self.other.pk)
            load.assert_not_called()

    def test_audio_estimate_uses_target_frames_and_seeded_sample_order(self):
        from modelanvil.runners.training.preflight_report import estimate_from_pilot
        pins={'steps':2,'config':{'model_role':'text_to_speech'},'sample_order':'seeded_epoch_shuffle_v1','initialization_seed':42}
        result=estimate_from_pilot({'pins':pins,'sequences':[[1,2]],'samples':[{'mel_frames':129}]},tenant=self.tenant.pk,project=self.project.pk,pool=None)
        self.assertEqual(result['total_tokens'],258);self.assertEqual(result['units']['tokens'],'target mel frames')
        self.assertFalse(result['known'])

    def test_forged_wave_measurements_and_silence_fail_the_trusted_output_boundary(self):
        import importlib.util
        if not importlib.util.find_spec('soundfile') or not importlib.util.find_spec('scipy'):
            self.skipTest('Optional audio media dependencies are absent.')
        from .test_audio_math import AudioBoundsTests
        import hashlib
        raw=AudioBoundsTests().audio(rate=16000,channels=1,seconds=.5)
        frozen={'settings':{'seed':42,'max_seconds':6},'plan':{'files':{}}}
        report={'schema_version':'modelanvil.independent-audio-generation.v1','frames':8000,'duration_seconds':.5,
            'sample_rate':16000,'channels':1,'sample_format':'PCM_S16_LE','seed':42,'maximum_seconds':6,
            'wave_sha256':hashlib.sha256(raw).hexdigest(),'wave_bytes':len(raw),'file_sha256':{},
            'consumer_imported_modelanvil_or_django':False,'prompt_tokens':10,'finish_reason':'stop',
            'cpu_seconds':1.,'wall_seconds':2.,'rms_before_quantization':.1,'clipped_fraction':0.,'last_stop_probability_sum':.9}
        self.assertEqual(audio.validate_output(raw,report,frozen)['frames'],8000)
        for update in ({'frames':True},{'sample_rate':48000},{'channels':2},{'wave_bytes':0},{'cpu_seconds':float('nan')},
                {'finish_reason':'length'},{'last_stop_probability_sum':.1},{'wave_sha256':'f'*64},{'consumer_imported_modelanvil_or_django':True}):
            with self.subTest(update=update),self.assertRaises(ValueError):audio.validate_output(raw,{**report,**update},frozen)
        import wave
        stream=io.BytesIO()
        with wave.open(stream,'wb') as output:
            output.setparams((1,2,16000,0,'NONE','not compressed'));output.writeframes(b'\0'*16000)
        silent=stream.getvalue()
        with self.assertRaises(ValueError):audio.validate_output(silent,{**report,'wave_sha256':hashlib.sha256(silent).hexdigest(),'wave_bytes':len(silent)},frozen)

    def test_independent_word_error_counts_include_insertions_deletions_and_case_normalization(self):
        from scripts.score_audio_candidate import word_errors
        self.assertEqual(word_errors('Please call Stella.','please call stella'),(0,3))
        self.assertEqual(word_errors('Please call Stella.','Please call'),(1,3))
        self.assertEqual(word_errors('Please call Stella.','Please call Stella now'),(1,3))
        self.assertEqual(word_errors('Please call Stella.','Please phone Bella'),(2,3))
        with self.assertRaises(ValueError):word_errors('!','hello')

    def test_shared_update_source_changes_invalidate_loaded_audio_build(self):
        from pathlib import Path
        original=Path.read_bytes
        def changed(path):
            raw=original(path)
            return raw+b'\nchanged' if str(path).endswith('/alignment/torch_rlhf.py') else raw
        with patch.object(Path,'read_bytes',changed):
            with self.assertRaisesRegex(ValueError,'changed on disk'):runtime.build_digest()
        self.assertEqual(runtime.build_digest(),runtime._BUILD_DIGEST)

    def test_text_comparison_refuses_speech_with_the_audio_quality_gate_reason(self):
        from types import SimpleNamespace
        from modelanvil.runners.guided_comparison import _guard
        with self.assertRaisesRegex(ValueError,'independent audio evaluation'):
            _guard(SimpleNamespace(hardware_config={'pins':{'config':{'model_role':'text_to_speech'}}}))
