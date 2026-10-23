import json
import os
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase,TransactionTestCase,tag
from modelanvil.core.ids import uuid7
from modelanvil.core.tenancy import reset_context
from modelanvil.rag.metrics import compute_all_retrieval_metrics
from modelanvil.rag.benchmark_corpus import select,PROTOCOL
from modelanvil.rag.models import IndexVersion,KnowledgeBase
from modelanvil.rag.retrieval import RetrievalEngine
from modelanvil.identity.models import Tenant


class RetrievalControlGuards(SimpleTestCase):
    def test_document_fixture_and_unlabeled_na(self):
        result=compute_all_retrieval_metrics(['B','X','A'],{'A','B','C'},{'A':1,'B':1,'C':1},3)
        self.assertAlmostEqual(result['recall@3'],2/3,places=4)
        self.assertAlmostEqual(result['precision@3'],2/3,places=4)
        self.assertEqual(result['mrr@3'],1)
        self.assertTrue(all(value is None for value in compute_all_retrieval_metrics(['B','X','A'],set(),{},3).values()))

    def test_source_group_selection_is_deterministic_and_keeps_positives(self):
        docs={str(i):{'doc_id':i} for i in range(1,31)}
        claims=[{'id':i,'claim':f'Fixture claim {i}','evidence':{str(i):[]},'cited_doc_ids':[i]} for i in range(1,31)]
        claims[0]['cited_doc_ids']=[1,2]
        with patch.dict(PROTOCOL,queries_per_split=2,document_count=8):
            selected,queries=select(docs,claims)
            self.assertEqual((selected,queries),select(docs,list(reversed(claims))))
            groups={role:{q['source_group'] for q in queries if q['role']==role} for role in ['development','held_out']}
            self.assertFalse(groups['development']&groups['held_out'])
            self.assertTrue({key for q in queries for key in q['relevant']}<={str(d['doc_id']) for d in selected})

    def test_search_effort_has_a_bounded_explicit_receipt(self):
        engine=RetrievalEngine(IndexVersion(tenant_id=uuid7(),configuration={}))
        self.assertEqual(engine.settings(5,ef_search=10)['hnsw']['ef_search'],10)
        for value in [0,1001,True,'10']:
            with self.assertRaises(ValueError):engine.settings(5,ef_search=value)


@tag('pg')
class ActualPublicRetrievalControls(TransactionTestCase):
    def test_frozen_public_corpus_controls_ann_recall_and_owned_cleanup(self):
        reset_context();self.addCleanup(reset_context)
        canary=Tenant.objects.create(slug='retain-unrelated-tenant',name='Retained unrelated data')
        base=KnowledgeBase.all_objects.create(tenant_id=canary.pk,name='Retained unrelated knowledge')
        from modelanvil.rag.benchmark import benchmark
        from modelanvil.rag.benchmark_corpus import load,select,PINS
        corpus,claims=load();docs,queries=select(corpus,claims)
        plan=json.loads((Path(__file__).resolve().parents[2]/'docs/engineering/verification/task69-retrieval-controls-2026-10-23/frozen-plan.json').read_text())
        self.assertEqual(plan['document_ids'],[str(d['doc_id']) for d in docs])
        self.assertEqual(plan['queries'],[{k:v for k,v in row.items() if k!='query'} for row in queries])
        self.assertEqual(plan['corpus_sha256'],PINS['sha256'])
        self.assertEqual(plan['protocol'],PROTOCOL)
        result=benchmark()
        self.assertTrue(KnowledgeBase.all_objects.filter(pk=base.pk,tenant_id=canary.pk).exists())
        self.assertEqual(Tenant.objects.count(),1)
        self.assertFalse(result['ann_neighbor_recall']['exact_fallback_enabled'])
        self.assertEqual(result['held_out']['real']['queries_total'],20)
        path=os.environ.get('MODELANVIL_RETRIEVAL_REPORT')
        if path:
            with Path(path).open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
        self.assertTrue(result['passed'],json.dumps({k:result[k] for k in ['held_out','frozen_thresholds']}))
        print('TASK69_CONTROLS '+json.dumps({'passed':result['passed'],'documents':result['documents'],'chunks':result['chunks'],
            'development_ndcg':{m:r['metrics']['ndcg@5'] for m,r in result['development'].items()},
            'held_out_ndcg':{m:r['metrics']['ndcg@5'] for m,r in result['held_out'].items()},
            'thresholds':result['frozen_thresholds']}))
