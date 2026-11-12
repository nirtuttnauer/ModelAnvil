import json
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from django.test import SimpleTestCase,tag
from modelanvil.rag import benchmark_expanded as expanded
from modelanvil.rag.benchmark_corpus import PINS as ARCHIVE_PINS,PROTOCOL


def claim(identifier,text,cited,evidence=()):
    return {'id':identifier,'claim':text,'cited_doc_ids':list(cited),'evidence':{str(key):[] for key in evidence}}


class ExpandedCorpusGuards(SimpleTestCase):
    def test_new_policy_and_pins_keep_the_original_pins_and_protocol(self):
        policy,pins=expanded.policy(),expanded.pins()
        self.assertEqual(policy['id'],'rag-expanded-corpus-v1')
        self.assertEqual(policy['label'],'small correctness check')
        self.assertEqual(pins['policy'],policy['id'])
        # The original archive pin and 200-document protocol stay as they were.
        self.assertEqual(pins['archive']['sha256'],ARCHIVE_PINS['sha256'])
        self.assertEqual(pins['archive']['license_sha256'],ARCHIVE_PINS['license_sha256'])
        self.assertEqual((PROTOCOL['version'],PROTOCOL['document_count'],PROTOCOL['queries_per_split']),
            ('scifact-bounded-source-groups-v1',200,20))
        self.assertEqual(pins['corpus']['records'],policy['size']['documents'])
        self.assertEqual(pins['corpus']['license'],'ODC-By-1.0')
        for role in expanded.ROLES:
            qrels=pins['qrels'][role]
            self.assertEqual((qrels['queries'],qrels['judgments']),(policy['size'][f'{role}_queries'],policy['size'][f'{role}_judgments']))
        self.assertEqual({p['license'] for p in pins['claims'].values()},{'CC-BY-4.0'})
        beir=pins['qrels']['held_out']['beir_cross_check']
        self.assertEqual(beir['sha256'],pins['qrels']['held_out']['sha256'])
        self.assertTrue(beir['url'].startswith('https://huggingface.co/datasets/BeIR/scifact-qrels/raw/'+beir['revision']+'/'))

    def test_every_test_claim_is_held_out_and_groups_do_not_cross(self):
        corpus=[{'doc_id':i,'title':f'T{i}','abstract':[f'A{i}']} for i in range(1,9)]
        train=[claim(10,'Shares a document',[1]),claim(11,'Linked through evidence',[5],[2]),
            claim(12,'held claim text',[6]),claim(13,'Independent  claim',[7,7]),claim(14,'Another one',[8])]
        test=[claim(20,'Held claim TEXT',[1,1,3]),claim(21,'Second held',[2,4])]
        docs,queries=expanded.select(corpus,train,test)
        roles={q['id']:q['role'] for q in queries}
        self.assertEqual({k for k,v in roles.items() if v=='held_out'},{'20','21'})
        # 10 shares document 1, 11 reaches document 2 through evidence, 12 repeats a held-out text.
        self.assertEqual({k for k,v in roles.items() if v=='development'},{'13','14'})
        self.assertEqual(next(q for q in queries if q['id']=='20')['relevant'],['1','3'])
        self.assertEqual(next(q for q in queries if q['id']=='13')['relevant'],['7'])
        groups={role:{q['source_group'] for q in queries if q['role']==role} for role in expanded.ROLES}
        self.assertFalse(groups['development']&groups['held_out'])
        self.assertEqual(queries,expanded.select(corpus,list(reversed(train)),test)[1])
        with self.assertRaises(ValueError):expanded.select(corpus,train+[claim(20,'Repeated ID',[8])],test)
        with self.assertRaises(ValueError):expanded.select(corpus,[claim(30,'Missing document',[99])],test)

    def test_judgments_use_the_beir_qrels_layout(self):
        data=expanded.qrels_tsv([claim(1,'a',[5,3,5]),claim(2,'b',[9])])
        self.assertEqual(data,b'query-id\tcorpus-id\tscore\r\n1\t5\t1\r\n1\t3\t1\r\n2\t9\t1\r\n')

    def test_shard_merge_equals_one_ranking_over_all_chunks(self):
        rows=[SimpleNamespace(chunk_id=f'{i:04x}',score=score) for i,score in enumerate([.9,.5,.5,.7,.1,.9,.3,.8,.5,.2,.6,.4])]
        shards=[rows[0::3],rows[1::3],rows[2::3]]
        for limit in [1,3,5,12]:
            per_shard=[sorted(s,key=lambda r:(-r.score,r.chunk_id))[:limit] for s in shards]
            expected=sorted(rows,key=lambda r:(-r.score,r.chunk_id))[:limit]
            self.assertEqual(expanded.merged(per_shard,limit),expected)
        self.assertEqual(expanded.shard_of('4983',5),int(expanded.ordered_key('shard','4983')[:8],16)%5)

    def test_frozen_inputs_must_be_committed_and_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args):subprocess.run(['git','-C',directory,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null',*args],check=True,capture_output=True)
            git('init','-q')
            frozen=root/'thresholds.json';frozen.write_text('{"minimum_relevance": 0.0}\n')
            with self.assertRaisesRegex(ValueError,'not committed'):expanded.committed(frozen,root)
            git('add','thresholds.json');git('commit','-q','-m','Freeze')
            sha=subprocess.run(['git','-C',directory,'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
            self.assertEqual(expanded.committed(frozen,root),sha)
            frozen.write_text('{"minimum_relevance": 0.5}\n')
            with self.assertRaisesRegex(ValueError,'differs from HEAD'):expanded.committed(frozen,root)
            with self.assertRaisesRegex(ValueError,'outside the repository'):expanded.committed(Path(tempfile.gettempdir())/'elsewhere.json',root)

    def test_reports_store_digests_as_json_unicode_escapes(self):
        value={'sha256':'ab'*32,'commit':'cd'*20,'nested':['ef'*32]}
        text=expanded.dumps(value)
        self.assertEqual(json.loads(text),value)
        self.assertIsNone(re.search(r'[0-9a-f]{64}',text))
        self.assertIn('cd'*20,text)

    def test_only_a_qualified_development_report_can_be_frozen(self):
        report={'phase':'development','ready_to_freeze':True,'policy_id':'rag-expanded-corpus-v1','plan_digest':'p','commit':'c',
            'thresholds':{'minimum_relevance':0.01,'chosen_ef_search':40},
            'relevance':{mode:{'metrics':{'ndcg@5':value}} for mode,value in zip(expanded.MODES,[.6,.01,0.0])}}
        frozen=expanded.freeze(report,b'report')
        self.assertEqual((frozen['source_phase'],frozen['thresholds']),('development',report['thresholds']))
        self.assertEqual(frozen['development_report_sha256'],expanded.sha256(b'report'))
        for change in [{'phase':'held_out'},{'ready_to_freeze':False}]:
            with self.assertRaises(ValueError):expanded.freeze({**report,**change},b'report')


@tag('pg')
class ExpandedPublicPlan(SimpleTestCase):
    """Needs the cached public archive, which the PostgreSQL environment provides."""

    def test_pinned_members_rebuild_the_committed_plan_and_beir_test_qrels(self):
        plan,docs,queries=expanded.build_plan()
        self.assertEqual(plan,json.loads(expanded.PLAN_PATH.read_text()))
        self.assertEqual(plan['qrels_sha256']['held_out'],expanded.pins()['qrels']['held_out']['beir_cross_check']['sha256'])
        self.assertEqual(len(docs),5183)
        self.assertEqual(sum(s['documents'] for s in plan['shards']),5183)
        self.assertTrue(all(s['source_text_bytes']<=expanded.MAX_SOURCE_BYTES for s in plan['shards']))
        self.assertEqual(sum(q['role']=='held_out' for q in queries),300)
