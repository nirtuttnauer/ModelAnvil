"""Image admission rejects untrusted media before model allocation."""
import io
import uuid
from unittest import skipUnless
from importlib.util import find_spec
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from modelanvil.runners.training import test_hf_runtime as fixtures
from modelanvil.identity.models import ApiKey, Role, generate_api_key
from modelanvil.artifacts.models import Artifact


@skipUnless(find_spec('PIL'), 'Optional image runtime is not installed')
class VisionChatAdmissionTests(TestCase):
    setUp = fixtures.GPUInputTests.setUp
    store = fixtures.GPUInputTests.store

    def api_client(self):
        secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Vision admission', role=Role.ENGINEER, secret_hash=hashed)
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        return client

    def test_valid_image_is_scoped_and_hashed_without_model_loading(self):
        from PIL import Image
        raw = io.BytesIO(); Image.new('RGB',(32,16),'red').save(raw,format='PNG'); raw = raw.getvalue()
        with patch('modelanvil.runners.training.vlm_math.load_model') as load:
            response = self.api_client().post('/api/v1/inference/models/upload-image/', {'file': SimpleUploadedFile('x.png',raw,content_type='image/png')}, format='multipart')
        self.assertEqual(response.status_code,201,response.content); load.assert_not_called()
        artifact = Artifact.all_objects.get(artifact_id=response.data['artifact_id'])
        self.assertEqual(artifact.project_id,self.project.pk)
        self.assertEqual(response.data['image']['decoded_width'],32)
        self.assertEqual(response.data['image']['sha256'],artifact.sha256)

    def test_bad_media_never_creates_artifact_or_loads_model(self):
        from PIL import Image
        oversized=io.BytesIO();Image.new('RGB',(1025,1),'red').save(oversized,format='PNG')
        client=self.api_client();before=Artifact.all_objects.count()
        for raw in (b'not an image',b'\x89PNG\r\n\x1a\ntruncated',oversized.getvalue(),b'x'*(2*1024**2+1)):
            with patch('modelanvil.runners.training.vlm_math.load_model') as load:
                response=client.post('/api/v1/inference/models/upload-image/',{'file':SimpleUploadedFile('image.png',raw,content_type='image/png')},format='multipart')
            self.assertEqual(response.status_code,400,response.content);load.assert_not_called()
            self.assertEqual(Artifact.all_objects.count(),before)

    def test_image_requests_cannot_enter_text_only_comparison_review(self):
        import hashlib
        from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion, InferenceRequest, ChatConversation, ChatComparison
        from modelanvil.runners.training.runtime import digest
        client = self.api_client()
        messages = [{'role': 'user', 'content': 'What color?'}]
        tokenizer = TokenizerVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Fixture')
        records = []
        for i in range(2):
            version = ModelVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
                model=Model.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name=f'Fixture {i}'), tokenizer=tokenizer)
            record = InferenceRequest.all_objects.create(tenant_id=self.tenant.pk, project=self.project, model_version=version,
                principal_id=str(self.key.pk), status='completed', input_digest=digest(messages),
                output_digest=hashlib.sha256(b'Red').hexdigest(), configuration={'image_artifact': str(uuid.uuid4())})
            records.append({'request_id': str(record.request_id), 'text': 'Red'})
        conversation = ChatConversation.all_objects.create(tenant_id=self.tenant.pk, project=self.project, title='Vision fixture')
        response = client.post('/api/v1/chat-comparisons/', {'conversation_id': str(conversation.conversation_id),
            'messages': messages, 'responses': records}, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(b'separate visual review workflow', response.content)
        self.assertEqual(ChatComparison.all_objects.count(), 0)
