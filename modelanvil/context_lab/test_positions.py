"""Software scoring guards and real pinned-model position runs."""
import json
import os
import tempfile
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase,TransactionTestCase,override_settings,tag
from modelanvil.context_lab.positions import PROTOCOL,messages,normalize,run,summarize
from modelanvil.core.tenancy import reset_context,set_active_tenant,set_active_project
from modelanvil.identity.models import Tenant,Team,Project
from modelanvil.rag.decoder import register


class PositionProtocolGuards(SimpleTestCase):
    def test_accuracy_comes_from_outputs_and_middle_dip_is_not_assumed(self):
        self.assertEqual(normalize('  WILLOW.\n'),'willow')
        self.assertNotEqual(normalize('The code is WILLOW.'),'willow')
        rows=[{'position':p,'repeat':repeat,'case_id':c['case_id'],'output':c['expected'],'correct':True}
            for p in PROTOCOL['positions'] for repeat in range(PROTOCOL['repeats']) for c in PROTOCOL['cases']]
        measured=summarize(rows)
        self.assertFalse(measured['middle_dip_observed'])
        self.assertTrue(all(v['accuracy']==1 and v['repeat_accuracy_stddev']==0 for v in measured['positions'].values()))
        rows[6]['correct']=False
        measured=summarize(rows)
        self.assertTrue(measured['middle_dip_observed']);self.assertGreater(measured['positions']['middle']['repeat_accuracy_stddev'],0)

    def test_only_fact_position_changes_and_all_evidence_is_retained(self):
        case=PROTOCOL['cases'][0];texts=[messages(case,p)[1]['content'] for p in PROTOCOL['positions']]
        self.assertTrue(texts[0].index(case['fact'])<texts[1].index(case['fact'])<texts[2].index(case['fact']))
        for text in texts:
            self.assertEqual(text.count(case['fact']),1)
            self.assertTrue(all(PROTOCOL['distractor'].format(number=n+1) in text for n in range(PROTOCOL['distractor_count'])))


@tag('pg')
class ActualPositionSweepTests(TransactionTestCase):
    def test_actual_pinned_model_repeats_positions_and_records_output_scoring(self):
        reset_context();self.addCleanup(reset_context)
        with tempfile.TemporaryDirectory(prefix='actual-position-') as root,override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':root}):
            tenant=Tenant.objects.create(slug='actual-position',name='Actual position fixture')
            team=Team.all_objects.create(tenant_id=tenant.pk,name='Team',slug='team')
            project=Project.all_objects.create(tenant_id=tenant.pk,team=team,name='Project',slug='project')
            set_active_tenant(tenant.pk);set_active_project(project.pk)
            report=run(register(project))
            self.assertEqual(len(report['runs']),18)
            for row in report['runs']:
                self.assertEqual(row['correct'],normalize(row['output'])==normalize(row['expected']))
                self.assertTrue(row['evidence_fact_retained'])
                self.assertEqual(row['input_tokens'],row['usage']['prompt_tokens'])
                self.assertLessEqual(row['input_tokens']+row['output_reserve_tokens'],row['runtime_limit_tokens'])
            self.assertEqual(report['summary'],summarize(report['runs']))
            for case in PROTOCOL['cases']:
                for position in PROTOCOL['positions']:
                    rows=[r for r in report['runs'] if r['case_id']==case['case_id'] and r['position']==position]
                    self.assertEqual(len({r['prompt_sha256'] for r in rows}),1)
            output=os.environ.get('MODELANVIL_POSITION_REPORT')
            if output:
                with Path(output).open('x') as stream:json.dump(report,stream,indent=2)
            print('TASK71_ACTUAL '+json.dumps(report['summary']))
