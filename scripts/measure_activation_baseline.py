#!/usr/bin/env python3
"""Measure a real CPU journey in a new, disposable database; never touches user data.

Run with the repository's Python environment. --serve keeps the disposable fixture
alive for browser QA; its sign-in details are written only to the private temp folder.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--serve', type=int, help='Optional loopback API port for browser QA')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='modelanvil-activation-') as directory:
        os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(Path(directory)/'pilot.sqlite3'),
                          MODELANVIL_ARTIFACT_ROOT=str(Path(directory)/'artifacts'), DJANGO_DEBUG='1')
        import django
        django.setup()
        from django.core.management import call_command
        from django.utils import timezone
        from modelanvil.api.test_activation import ActivationTests
        from modelanvil.build_info import build_info
        from modelanvil.core.activation import activation_report
        from modelanvil.identity.models import Membership, Role, User
        from modelanvil.jobs.executor import execute_claim
        from modelanvil.jobs.models import claim_job
        from modelanvil.runners.eval_worker import evaluation_worker_executor
        from modelanvil.runners.models import EvaluationRun
        call_command('migrate', verbosity=0, interactive=False)
        migrated = time.perf_counter()
        pilot = ActivationTests()
        try:
            pilot.setUp()  # Real two-step transformer training and fenced baseline/candidate evaluation.
            prepared = time.perf_counter()
            opened = pilot.event()
            assert opened.status_code == 201, opened.content
            response = pilot.client.post(pilot.url, {'outcome': 'reject'}, format='json', **pilot.headers)
            assert response.status_code == 201, response.content
            report = activation_report(pilot.tenant.pk, pilot.project)
            assert report['weekly_improvement_cycles'] == 1 and report['weekly_accepted_improvements'] == 0
            candidate_pins = pilot.evaluation.protocol_ref['pins']['candidate']
            hardware = {'os': platform.platform(), 'architecture': platform.machine(), 'cpu_model': platform.processor() or None}
            if sys.platform == 'darwin':
                hardware['cpu_model'] = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip()
                hardware['physical_memory_bytes'] = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.memsize'], text=True))
            result = {'observed_at': timezone.now().isoformat(), 'scope': 'automated_fresh_database_cpu_reference',
                'build': build_info(), 'python': platform.python_version(), 'machine': platform.machine(),
                'hardware': hardware,
                'fresh_database': True, 'fresh_artifacts': True, 'dependency_installation_seconds': None,
                'model_download_seconds': None, 'human_active_seconds': None,
                'missing_timing_reason': 'Existing Python dependencies and initialized local reference weights; no model download or human onboarding observed.',
                'migration_seconds': migrated - started, 'resource_training_evaluation_seconds': prepared - migrated,
                'fresh_database_to_decision_seconds': time.perf_counter() - started,
                'candidate_pins': candidate_pins, 'evaluation_pins': pilot.evaluation.protocol_ref['pins'],
                'committed_steps': 2, 'evaluation_cases': 1, 'decision': 'reject', 'report': report,
                'quality_claim': 'None. This is a one-case workflow baseline with a deliberately failing candidate, not useful-model qualification.'}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps({'report': str(args.output.resolve()), 'cycle_count': 1,
                              'elapsed_seconds': result['fresh_database_to_decision_seconds']}), flush=True)
            if args.serve:
                # A second actual comparison is undecided so the browser can exercise the new controls.
                r = pilot.client.post('/api/v1/evaluation-runs/', {
                    'suite_version': pilot.evaluation.suite_version_id, 'candidate_model_version': pilot.candidate.pk,
                    'baseline_model_version': pilot.base.pk}, format='json', **pilot.headers)
                assert r.status_code == 201, r.content
                evaluation = EvaluationRun.all_objects.get(run_id=r.data['run_id'])
                r = pilot.client.post(f'/api/v1/evaluation-runs/{evaluation.run_id}/execute/',
                                     pilot.request, format='json', **pilot.headers)
                assert r.status_code == 202, r.content
                evaluation.refresh_from_db()
                outcome = execute_claim(pilot.evaluator, claim_job(pilot.evaluator, evaluation.job), evaluation_worker_executor)
                assert outcome['status'] == 'succeeded', outcome
                password = 'Local-Pilot-Only-44!'
                user = User.objects.create_user(email='task44@example.test', password=password, name='Local activation pilot')
                Membership.objects.create(tenant=pilot.tenant, user=user, role=Role.OWNER)
                credentials = Path(directory)/'browser.json'
                credentials.write_text(json.dumps({'email': user.email, 'password': password,
                                                   'project': str(pilot.project.pk), 'evaluation': str(evaluation.run_id)}))
                credentials.chmod(0o600)
                print(json.dumps({'loopback_api': f'http://127.0.0.1:{args.serve}',
                                  'private_browser_fixture': str(credentials)}), flush=True)
                call_command('runserver', f'127.0.0.1:{args.serve}', use_reloader=False)
        finally:
            pilot.doCleanups()


if __name__ == '__main__':
    main()
