"""Exact source reconstruction, actual token budgets and immutable recipe reuse."""
import hashlib
import random
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient
from modelanvil.identity.models import Tenant, ApiKey, Role, generate_api_key
from modelanvil.rag.chunking import PINS, TOKENIZER_SHA256, encode, token_chunks, tokenizer
from modelanvil.rag.models import SourceDocument, DocumentChunk, IndexVersion


class TokenWindowTests(SimpleTestCase):
    def assert_windows(self, text, size, overlap):
        rows = list(token_chunks(text, size, overlap))
        self.assertEqual(rows, list(token_chunks(text, size, overlap)))
        cursor = 0; reconstructed = ''
        for row in rows:
            start, end = row['span_start'], row['span_end']
            self.assertLessEqual(start, cursor); self.assertGreater(end, cursor)
            self.assertEqual(row['text'], text[start:end])
            self.assertEqual(row['token_count'], len(encode(row['text']).ids))
            self.assertLessEqual(row['token_count'], size)
            actual_overlap = len(encode(text[start:cursor]).ids) if start < cursor else 0
            self.assertEqual(row['metadata']['overlap_tokens'], actual_overlap)
            self.assertLessEqual(actual_overlap, overlap)
            reconstructed += row['text'][cursor-start:]; cursor = end
        self.assertEqual(cursor, len(text)); self.assertEqual(reconstructed, text)
        return rows

    def test_offline_exact_unicode_offsets_and_actual_budgets(self):
        text = '\t  Café a\u0301 naïve 日本語 👩🏽‍💻.\n\n' + ('multilingual uncharacteristically hyperparameterization? ' * 30) + '\r\n  '
        with patch('socket.socket.connect', side_effect=AssertionError('No network allowed')):
            rows = self.assert_windows(text, 19, 7)
        self.assertGreater(len(rows), 10)
        self.assertEqual(rows[0]['metadata']['tokenizer']['sha256'], TOKENIZER_SHA256)
        for overlap in [0, 8]:self.assert_windows(text, 16, overlap)

    def test_seeded_text_with_normalization_punctuation_and_overlapping_windows(self):
        randomizer = random.Random(66)
        vocabulary = ['words', 'a\u0301', '日本語', '👩🏽‍💻', '\u200b', 'uncharacteristically', '!', '\n\n', '\t', '  ', '\x00']
        for number in range(30):
            text = 'Source ' + ''.join(randomizer.choice(vocabulary) for _ in range(150)) + ' end.  '
            with self.subTest(number=number):self.assert_windows(text, 16+number, number//3)

    def test_preference_for_paragraph_then_sentence_before_hard_limit(self):
        paragraph = ' '.join(['alpha']*12) + '\n\n'
        text = paragraph + ' '.join(['beta']*40)
        rows = self.assert_windows(text, 20, 2)
        self.assertEqual(rows[0]['span_end'], len(paragraph))
        sentence = ' '.join(['alpha']*12) + '. '
        rows = self.assert_windows(sentence + ' '.join(['beta']*40), 20, 2)
        self.assertEqual(rows[0]['span_end'], len(sentence))

    def test_corrupt_bundled_bytes_and_invisible_sources_fail_closed(self):
        tokenizer.cache_clear()
        try:
            with patch('pathlib.Path.read_bytes', return_value=b'changed'):
                with self.assertRaisesRegex(ValueError, 'checksum'):tokenizer()
        finally:tokenizer.cache_clear()
        with self.assertRaisesRegex(ValueError, 'visible'):list(token_chunks('\u200b\x00',16,0))
        for size, overlap in [(0,0),(16,9),(True,0),(17,-1)]:
            with self.assertRaises(ValueError):list(token_chunks('text',size,overlap))


class TokenIndexTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(slug='token-index',name='Token index')
        secret, hashed = generate_api_key(); ApiKey.objects.create(tenant=tenant,name='Author',role=Role.ENGINEER,secret_hash=hashed)
        self.client = APIClient();self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        result=self.client.post('/api/v1/knowledge-bases/',{'name':'Token sources'},format='json')
        self.assertEqual(result.status_code,201,result.data)
        self.path=f'/api/v1/knowledge-bases/{result.data["knowledge_base_id"]}/index/'
        self.text='  '+('Source paragraph with complex multilingual evidence. '*25)+'\n\n'+('Second paragraph café 日本語. '*20)+'  '

    def build(self, size=32, overlap=8, documents=None):
        response=self.client.post(self.path,{'documents':documents or [{'title':'Source','source_uri':'local:same','content':self.text}], 'chunk_size':size,'chunk_overlap':overlap},format='json')
        self.assertEqual(response.status_code,201,response.data)
        return IndexVersion.all_objects.get(index_id=response.data['index_id'])

    def test_reimport_has_same_chunks_hashes_and_no_new_document_revision(self):
        first=self.build();second=self.build()
        self.assertEqual(SourceDocument.all_objects.count(),1)
        self.assertEqual(first.configuration['chunk_ids'],second.configuration['chunk_ids'])
        self.assertEqual(first.manifest_digest,second.manifest_digest)
        self.assertEqual(first.configuration['tokenizer'],PINS)
        self.assertEqual(first.configuration['chunk_units'],'tokens')
        for chunk in DocumentChunk.all_objects.all():
            self.assertEqual(chunk.content_hash,hashlib.sha256(self.text[chunk.span_start:chunk.span_end].encode()).hexdigest())
            self.assertEqual(chunk.token_count,len(encode(chunk.text).ids))

    def test_rechunk_reuses_source_revision_and_retains_old_frozen_membership(self):
        first=self.build();old=list(DocumentChunk.all_objects.filter(chunk_id__in=first.configuration['chunk_ids']).values('chunk_id','content_hash','text'))
        second=self.build(20,3)
        self.assertEqual(SourceDocument.all_objects.count(),1)
        self.assertNotEqual(first.configuration['chunk_recipe_digest'],second.configuration['chunk_recipe_digest'])
        self.assertFalse(set(first.configuration['chunk_ids']) & set(second.configuration['chunk_ids']))
        self.assertEqual(old,list(DocumentChunk.all_objects.filter(chunk_id__in=first.configuration['chunk_ids']).values('chunk_id','content_hash','text')))
        third=self.build(20,3);self.assertEqual(third.manifest_digest,second.manifest_digest)

    def test_other_active_sources_are_rechunked_without_silent_loss(self):
        self.build()
        second=self.build(20,3,[{'title':'Other','source_uri':'local:other','content':'Other short source.'}])
        documents=set(DocumentChunk.all_objects.filter(chunk_id__in=second.configuration['chunk_ids']).values_list('document__source_uri',flat=True))
        self.assertEqual(documents,{'local:same','local:other'})
        self.assertEqual(SourceDocument.all_objects.count(),2)

    def test_legacy_character_chunks_survive_but_do_not_enter_token_snapshot(self):
        index=self.build();document=SourceDocument.all_objects.get()
        legacy=DocumentChunk.all_objects.create(tenant_id=document.tenant_id,document=document,chunk_index=0,text='legacy',content_hash=hashlib.sha256(b'legacy').hexdigest())
        current=self.build(20,3)
        self.assertNotIn(str(legacy.chunk_id),current.configuration['chunk_ids'])
        self.assertTrue(DocumentChunk.all_objects.filter(pk=legacy.pk).exists())

    def test_failed_tokenization_rolls_back_documents_chunks_and_index(self):
        with patch('modelanvil.rag.ingestion.token_chunks',side_effect=ValueError('bounded refusal')):
            response=self.client.post(self.path,{'documents':[{'title':'Source','content':'Actual text'}]},format='json')
        self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(SourceDocument.all_objects.count(),0);self.assertEqual(DocumentChunk.all_objects.count(),0);self.assertEqual(IndexVersion.all_objects.count(),0)
