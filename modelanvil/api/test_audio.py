"""Audio API authorization and typed request boundaries; fixtures do not qualify quality."""
import io
import math
import struct
import wave
from unittest.mock import patch
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from modelanvil.api import test_specialists as fixtures
from modelanvil.runners.models import InferenceRequest
from modelanvil.runners import audio_generation as audio
from modelanvil.jobs.models import Job,WorkerPool
from modelanvil.identity.models import Role


class AudioApiTests(TestCase):
    setUp=fixtures.SpecialistApiTests.setUp
    version=fixtures.SpecialistApiTests.version

    def test_typed_input_errors_never_allocate_and_catalog_excludes_text_models(self):
        r=self.client.get('/api/v1/audio/');self.assertEqual(r.status_code,200);self.assertEqual(r.data['models'],[])
        with patch.object(audio,'queue') as queue:
            for body in ({'text':'a'*97},{'model':'https://example.com/model'},{'max_seconds':20},{'executor':'shell'}):
                r=self.client.post('/api/v1/audio/jobs/',body,format='json');self.assertEqual(r.status_code,400)
            queue.assert_not_called()

    def test_upload_records_actual_normalization_and_rejects_invalid_or_oversize_bytes(self):
        try:import soundfile,scipy
        except ImportError:self.skipTest('Optional audio media dependencies are absent.')
        stream=io.BytesIO()
        with wave.open(stream,'wb') as output:
            output.setparams((1,2,8000,0,'NONE','not compressed'))
            output.writeframes(b''.join(struct.pack('<h',int(5000*math.sin(i/10))) for i in range(8000)))
        r=self.client.post('/api/v1/audio/upload-audio/',{'file':SimpleUploadedFile('sample.wav',stream.getvalue())},format='multipart')
        self.assertEqual(r.status_code,201,r.content)
        self.assertEqual(r.data['normalization']['sample_rate'],8000);self.assertEqual(r.data['normalization']['normalized_frames'],16000)
        self.assertEqual(r.data['artifact']['sha256'],r.data['normalization']['sha256'])
        for raw in (b'bad audio',b'0'*(4*1024**2+1)):
            r=self.client.post('/api/v1/audio/upload-audio/',{'file':SimpleUploadedFile('bad.wav',raw)},format='multipart');self.assertEqual(r.status_code,400)

    def test_other_request_kinds_cannot_be_polled_or_cancelled_and_viewers_cannot_write(self):
        record=InferenceRequest.all_objects.create(tenant_id=self.tenant.pk,project=self.project,model_version=self.model,principal_id='fixture',input_digest='a'*64,
            status='queued',configuration={'kind':'ocr','job_id':'not-an-audio-job'})
        self.assertEqual(self.client.get('/api/v1/audio/jobs/').data,[])
        self.assertEqual(self.client.get(f'/api/v1/audio/jobs/{record.request_id}/').status_code,404)
        self.assertEqual(self.client.post(f'/api/v1/audio/jobs/{record.request_id}/cancel/').status_code,404)
        self.key.role=Role.VIEWER;self.key.save(update_fields=['role'])
        self.assertEqual(self.client.post('/api/v1/audio/jobs/',{},format='json').status_code,403)

    def test_generic_job_api_cannot_mutate_create_delete_or_cancel_owned_audio_jobs(self):
        pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='audio')
        job=Job.all_objects.create(tenant_id=self.tenant.pk,project=self.project,pool=pool,name='speech',payload={'type':audio.TYPE,'request_id':'fixture'})
        for method,path,body in (('post','/api/v1/jobs/',{'name':'fake','pool':pool.pk,'payload':{'type':audio.TYPE}}),
                ('patch',f'/api/v1/jobs/{job.job_id}/',{'payload':{'type':'other'}}),('delete',f'/api/v1/jobs/{job.job_id}/',None),
                ('post',f'/api/v1/jobs/{job.job_id}/cancel/',{})):
            r=getattr(self.client,method)(path,body,format='json');self.assertIn(r.status_code,(400,404),r.content)
        job.refresh_from_db();self.assertEqual(job.payload['type'],audio.TYPE);self.assertEqual(job.status,'queued')
