"""Protected audio split and access boundaries; no speech quality claim."""
import hashlib
import json
import uuid
from unittest.mock import patch
from django.test import TestCase
from modelanvil.runners.training import test_hf_runtime as fixtures
from modelanvil.runners.training import audio_data as data
from modelanvil.artifacts.models import Dataset, DatasetRevision


class AudioDataGuards(TestCase):
    setUp = fixtures.GPUInputTests.setUp
    store = fixtures.GPUInputTests.store

    def test_source_speaker_encoded_and_normalized_duplicates_cannot_cross_splits(self):
        dataset=Dataset.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Audio')
        for revision_no,duplicate in enumerate(('group','speaker','raw','normalized'),1):
            rows=[];pins=[]
            for index in range(3):
                rows.append({'schema_version':'1.0','sample_id':str(uuid.uuid4()),
                    'source_group_id':'same' if duplicate=='group' else str(index),
                    'metadata':{'speaker_id':'same' if duplicate=='speaker' else str(index)},
                    'blocks':[{'block_id':'text','type':'text','role':'user','text':'Please call Stella.'},
                        {'block_id':'audio','type':'audio','role':'assistant','asset_ref':'artifact:'+str(self.artifact.artifact_id)}],
                    'provenance':{'source_snapshot_ref':'fixture','source_record_key':str(index),'content_sha256':self.artifact.sha256}})
                pins.append({'sha256':('a' if duplicate=='raw' else str(index))*64,
                    'normalized_sha256':('b' if duplicate=='normalized' else str(index))*64,
                    'media_type':'audio/wav','normalized_rms':.1})
            value={'rows':rows,'split_manifest':{split:[row['sample_id']] for split,row in zip(('train','validation','test'),rows)}}
            raw=json.dumps(value).encode();manifest=self.store(raw,'application/json')
            revision=DatasetRevision.all_objects.create(tenant_id=self.tenant.pk,project=self.project,dataset=dataset,
                revision_no=revision_no,state='published',manifest_artifact=manifest,manifest_digest=hashlib.sha256(raw).hexdigest())
            with self.subTest(duplicate=duplicate),patch.object(data,'read_audio',side_effect=[(None,pin) for pin in pins]), \
                    patch.object(data,'_features',return_value=(None,{'token_ids':[1,2],'mel_frames':4,'padded_mel_frames':4,'mel_sha256':'c'*64})):
                with self.assertRaisesRegex(ValueError,'cross protected splits'):data.samples(revision,object(),self.tenant.pk,self.project.pk)

    def test_scope_and_media_are_checked_before_decoding(self):
        with patch.object(data.audio_math,'decode_audio') as decode:
            with self.assertRaises(ValueError):data.read_audio(self.artifact.artifact_id,self.tenant.pk,self.other.pk)
            with self.assertRaises(ValueError):data.read_audio(self.artifact.artifact_id,self.tenant.pk,self.project.pk)
            with self.assertRaises(ValueError):data.read_audio('https://example.com/audio.wav',self.tenant.pk,self.project.pk)
            decode.assert_not_called()

    def test_supported_six_second_stereo_wav_can_exceed_reference_text_reader_limit(self):
        import importlib.util
        if not importlib.util.find_spec('soundfile') or not importlib.util.find_spec('scipy'):
            self.skipTest('Optional audio media dependencies are absent.')
        from .test_audio_math import AudioBoundsTests
        raw=AudioBoundsTests().audio(rate=48000,channels=2,seconds=6)
        self.assertGreater(len(raw),1024**2)
        artifact=self.store(raw,'audio/wav')
        values,pin=data.read_audio(artifact.artifact_id,self.tenant.pk,self.project.pk)
        self.assertEqual(len(values),96000);self.assertEqual(pin['duration_seconds'],6)
        self.assertEqual(pin['channels'],2)
