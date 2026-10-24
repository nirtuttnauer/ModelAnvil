"""Frozen corpus quotas/splits and contamination guards, without model score fixtures."""
import copy,hashlib,uuid
from django.test import SimpleTestCase
from modelanvil.data.continued_corpus import assemble

def source(prefix,weight):
    rows=[];splits={'train':[],'validation':[],'test':[]}
    for i in range(10):
        text=f'{prefix} unique fact number {i}.';identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,prefix+str(i)))
        row={'schema_version':'1.0','sample_id':identifier,'source_group_id':prefix+str(i),
            'blocks':[{'block_id':'text','type':'text','text':text}],
            'provenance':{'source_snapshot_ref':'authored:'+prefix,'source_record_key':str(i),'content_sha256':hashlib.sha256(text.encode()).hexdigest()}}
        rows.append(row);splits['train' if i<8 else 'validation' if i==8 else 'test'].append(identifier)
    return {'pin':{'revision_id':str(uuid.uuid5(uuid.NAMESPACE_URL,prefix)),'manifest_digest':hashlib.sha256(prefix.encode()).hexdigest()},'weight':weight,
        'prepared':{'rows':rows,'split_manifest':splits}}

class ContinuedCorpusGuards(SimpleTestCase):
    def test_weighted_order_is_deterministic_and_preserves_original_protected_splits(self):
        sources=[source('domain',3),source('protected',1)];before=copy.deepcopy(sources)
        first=assemble(sources,train_samples=8,seed='fixed');second=assemble(sources,train_samples=8,seed='fixed')
        self.assertEqual(first,second);self.assertEqual(sources,before)
        from contracts import validate_envelope
        for row in first['rows']:validate_envelope(row)
        self.assertEqual([c['train_quota'] for c in first['recipe']['components']],[6,2])
        self.assertEqual([c['normalized_weight'] for c in first['recipe']['components']],['3/4','1/4'])
        for split in ['validation','test']:
            self.assertEqual(first['split_manifest'][split],sum([s['prepared']['split_manifest'][split] for s in sources],[]))
        train=set(first['split_manifest']['train']);self.assertFalse(train & set(first['split_manifest']['validation']+first['split_manifest']['test']))
        self.assertNotEqual(first['split_manifest']['train'],assemble(sources,train_samples=8,seed='another')['split_manifest']['train'])

    def test_nonfinite_weights_empty_quota_and_shortage_never_rebalance(self):
        for weight in ['NaN','Infinity',0,-1,'0.0001',True]:
            with self.assertRaises(ValueError):assemble([source('domain',weight)],train_samples=4,seed='fixed')
        for count in [1,20]:
            with self.assertRaisesRegex(ValueError,'quotas'):assemble([source('domain',3),source('protected',1)],train_samples=count,seed='fixed')

    def test_cross_source_content_group_and_identifier_leaks_are_refused(self):
        for kind in ['text','group','identifier']:
            a,b=source('domain',1),source('protected',1)
            if kind=='text':b['prepared']['rows'][8]['blocks']=copy.deepcopy(a['prepared']['rows'][0]['blocks'])
            elif kind=='group':b['prepared']['rows'][8]['source_group_id']=a['prepared']['rows'][0]['source_group_id']
            else:
                old=b['prepared']['rows'][0]['sample_id'];new=a['prepared']['rows'][0]['sample_id'];b['prepared']['rows'][0]['sample_id']=new
                b['prepared']['split_manifest']['train'][0]=new
            with self.assertRaises(ValueError):assemble([a,b],train_samples=4,seed='fixed')

    def test_chat_and_empty_protected_splits_are_not_plain_corpus(self):
        a=source('domain',1);a['prepared']['rows'][0]['blocks'][0]['role']='assistant'
        with self.assertRaisesRegex(ValueError,'plain-text'):assemble([a],train_samples=4,seed='fixed')
        a=source('domain',1);a['prepared']['rows']=a['prepared']['rows'][:8];a['prepared']['split_manifest']['validation']=[];a['prepared']['split_manifest']['test']=[]
        with self.assertRaisesRegex(ValueError,'protected validation'):assemble([a],train_samples=4,seed='fixed')

import io,json,tempfile
from django.conf import settings
from django.test import TestCase,override_settings
from rest_framework.test import APIClient
from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import Tenant,Team,Project,ApiKey,Role,generate_api_key
from modelanvil.artifacts.models import Artifact,Dataset,DatasetRevision,DeletionTombstone,LineageEdge
from modelanvil.artifacts.storage import artifact_storage_backend,upload_staged_artifact
from modelanvil.data import continued_corpus as corpus

@override_settings(ALLOWED_HOSTS=['testserver'])
class ContinuedCorpusHTTPGuards(TestCase):
    def setUp(self):
        reset_context();self.addCleanup(reset_context);folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.enterContext(override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':folder.name}))
        self.tenant=Tenant.objects.create(name='Corpus tests',slug='corpus-tests')
        team=Team.all_objects.create(tenant_id=self.tenant.pk,name='Team',slug='team')
        self.project=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,name='One',slug='one')
        self.other=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,name='Other',slug='other')
        self.a=self.shard('domain');self.b=self.shard('protected')
        secret,hashed=generate_api_key();ApiKey.objects.create(tenant=self.tenant,project=self.project,name='Corpus owner',role=Role.OWNER,secret_hash=hashed)
        self.client=APIClient();self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret,HTTP_X_PROJECT_ID=str(self.project.pk))
        self.input={'name':'Weighted source corpus','components':[{'revision_id':str(self.a.revision_id),'weight':'3'},{'revision_id':str(self.b.revision_id),'weight':'1'}],'train_samples':8,'seed':'fixed'}
    def shard(self,name,project=None,chat=False):
        project=project or self.project;prepared=source(name,1)['prepared']
        if chat:prepared['rows'][8]['blocks'][0]['role']='assistant'
        raw=json.dumps(prepared).encode()
        artifact=Artifact.all_objects.create(tenant_id=self.tenant.pk,project=project,storage_location_id='local',object_key='corpus-test/'+str(uuid.uuid4()),sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),media_type='application/json')
        upload_staged_artifact(artifact,io.BytesIO(raw),backend=artifact_storage_backend())
        dataset=Dataset.all_objects.create(tenant_id=self.tenant.pk,project=project,name=name)
        return DatasetRevision.all_objects.create(tenant_id=self.tenant.pk,project=project,dataset=dataset,revision_no=1,state='published',manifest_digest=artifact.sha256,manifest_artifact=artifact,row_count=len(prepared['rows']))
    def test_actual_api_publication_binds_source_bytes_edges_and_protected_splits(self):
        response=self.client.post('/api/v1/pretraining-corpora/',self.input,format='json')
        self.assertEqual(response.status_code,201,response.content);value=response.json()
        self.assertEqual(value['split_counts'],{'train':8,'validation':2,'test':2})
        self.assertEqual([c['train_quota'] for c in value['recipe']['components']],[6,2])
        revision=DatasetRevision.all_objects.get(revision_id=value['revision_id'])
        self.assertEqual(LineageEdge.all_objects.filter(child_artifact=revision.manifest_artifact,relation='continued_corpus_source').count(),2)
        self.assertEqual(revision.manifest_digest,revision.manifest_artifact.sha256)
        listed=self.client.get('/api/v1/pretraining-corpora/');self.assertEqual(listed.status_code,200)
        self.assertEqual(len(listed.json()['results']),1);self.assertNotIn('unique fact',listed.content.decode())
        DeletionTombstone.all_objects.create(tenant_id=self.tenant.pk,resource_type='artifact',resource_id=str(self.a.manifest_artifact.artifact_id),reason='Revoke test source')
        self.assertEqual(self.client.get('/api/v1/pretraining-corpora/').json()['results'],[])
        with self.assertRaises(ValueError):corpus.pins(revision,self.tenant.pk,self.project.pk)
    def test_foreign_source_unknown_fields_bad_weight_and_duplicate_name_do_not_publish(self):
        foreign=self.shard('foreign',self.other)
        invalids=[{**self.input,'components':[{'revision_id':str(foreign.revision_id),'weight':'1'}]},
            {**self.input,'components':[{'revision_id':str(self.a.revision_id),'weight':'NaN'}]},
            {**self.input,'unsafe':True}]
        before=DatasetRevision.all_objects.count()
        for value in invalids:
            response=self.client.post('/api/v1/pretraining-corpora/',value,format='json');self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(DatasetRevision.all_objects.count(),before)
        self.assertEqual(self.client.post('/api/v1/pretraining-corpora/',self.input,format='json').status_code,201)
        self.assertEqual(self.client.post('/api/v1/pretraining-corpora/',self.input,format='json').status_code,400)

    def test_viewer_can_list_but_cannot_publish_corpora(self):
        secret,hashed=generate_api_key()
        ApiKey.objects.create(tenant=self.tenant,project=self.project,name='Read-only corpus viewer',role=Role.VIEWER,secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret,HTTP_X_PROJECT_ID=str(self.project.pk))
        self.assertEqual(self.client.get('/api/v1/pretraining-corpora/').status_code,200)
        before=DatasetRevision.all_objects.count()
        self.assertEqual(self.client.post('/api/v1/pretraining-corpora/',self.input,format='json').status_code,403)
        self.assertEqual(DatasetRevision.all_objects.count(),before)

    def test_single_shard_continued_pins_refuse_chat_in_protected_rows(self):
        mixed=self.shard('mixed-protected-chat',chat=True)
        with self.assertRaisesRegex(ValueError,'plain-text'):corpus.pins(mixed,self.tenant.pk,self.project.pk)
