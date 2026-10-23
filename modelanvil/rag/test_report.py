"""Fail-closed source/citation/reproduction guards for actual report composition."""
import copy
import json
from django.test import SimpleTestCase
from scripts.rag_report import ROOT,assemble,compare,table


def fixture():
    def load(name):return json.loads((ROOT/'docs/engineering/verification'/name/'actual-report.json').read_text())
    r=load('task69-retrieval-controls-2026-10-23');g=load('task70-grounded-generation-2026-10-23');p=load('task71-real-position-sweep-2026-10-23')
    context={'commit':'a'*40,'hardware':{'gpu_used':False}}
    r['commit']=p['source_commit']=context['commit'];g['provenance']=context
    return r,g,p,context


class CombinedReportGuards(SimpleTestCase):
    def test_mixed_source_and_unbound_citations_fail_without_cv_self_certification(self):
        r,g,p,context=fixture();report=assemble(r,g,p,context)
        self.assertFalse(report['cv_evidence_confirmed'])
        r['commit']='b'*40
        with self.assertRaisesRegex(ValueError,'exact source'):assemble(r,g,p,context)
        r['commit']=context['commit'];g['runs'][1]['citations'].append({'chunk_id':'invented'})
        with self.assertRaisesRegex(ValueError,'Unbound'):assemble(r,g,p,context)

    def test_real_metric_drift_or_schedule_changes_fail_frozen_reproduction(self):
        baseline=assemble(*fixture());current=copy.deepcopy(baseline)
        self.assertTrue(compare(baseline,current)['passed'])
        current['retrieval']['held_out']['real']['metrics']['ndcg@5']-=0.1
        with self.assertRaisesRegex(ValueError,'outside tolerance'):compare(baseline,current)
        current=copy.deepcopy(baseline);current['positions']['runs'][0]['prompt_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'prompt schedule'):compare(baseline,current)

    def test_public_table_values_come_from_the_report(self):
        report=assemble(*fixture());report['retrieval']['held_out']['real']['metrics']['ndcg@5']=0.1234
        report['positions']['summary']['middle_dip_observed']=True
        text=table(report)
        self.assertIn('0.1234',text);self.assertIn('middle dip observed',text)
        self.assertIn(report['provenance']['commit'],text)
