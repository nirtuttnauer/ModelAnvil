"""Controlled execution of one durable worker claim."""
import importlib
import importlib.util
import uuid
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job


def command_fixture_executor(descriptor, context):
    context.heartbeat(progress=0.25)
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.uuid4()),
        "source_group_id": "command-fixture",
        "blocks": [{"block_id": "b1", "type": "text", "text": descriptor["job_id"]}],
        "provenance": {
            "source_snapshot_ref": "fixture-snapshot",
            "source_record_key": "fixture-record",
            "content_sha256": "0" * 64,
        },
    }


class ControlledExecutorTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="executor-test", name="Executor Test")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="executor-worker",
            slots=1,
            capabilities={"accelerator": "cpu"},
        )
        self.job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="controlled task",
            payload={"value": 7},
            requirements={"accelerator": "cpu"},
        )

    def test_executor_runs_after_claim_and_commits_verified_result(self):
        spec = importlib.util.find_spec("modelanvil.jobs.executor")
        self.assertIsNotNone(spec, "controlled worker executor module is missing")
        execute_one = importlib.import_module("modelanvil.jobs.executor").execute_one
        result_envelope = {
            "schema_version": "1.0",
            "sample_id": str(uuid.uuid4()),
            "source_group_id": "executor-fixture",
            "blocks": [{"block_id": "b1", "type": "text", "text": "done"}],
            "provenance": {
                "source_snapshot_ref": "fixture-snapshot",
                "source_record_key": "fixture-record",
                "content_sha256": "0" * 64,
            },
        }
        observed = {}

        def executor(descriptor, context):
            observed["descriptor"] = descriptor
            observed["heartbeat"] = context.heartbeat(progress=0.5)
            return result_envelope

        outcome = execute_one(self.worker, executor)

        self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "succeeded"})
        self.assertEqual(observed["descriptor"]["payload"], {"value": 7})
        self.assertTrue(observed["heartbeat"])
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        attempt = JobAttempt.objects.get(job=self.job)
        self.assertEqual(self.job.status, Job.Status.SUCCEEDED)
        self.assertEqual(self.worker.slots, 1)
        self.assertEqual(attempt.status, JobAttempt.Status.SUCCEEDED)
        self.assertEqual(attempt.progress, 0.5)
        self.assertEqual(attempt.result_envelope, result_envelope)

    def test_run_worker_command_executes_one_job_with_configured_executor(self):
        output = StringIO()

        call_command(
            "run_worker",
            "--worker-id",
            str(self.worker.pk),
            "--executor",
            "modelanvil.jobs.test_executor.command_fixture_executor",
            "--once",
            stdout=output,
        )

        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.SUCCEEDED)
        self.assertEqual(self.worker.slots, 1)
        self.assertIn("succeeded", output.getvalue())
        self.assertIsNotNone(self.worker.last_heartbeat_at)
        self.assertEqual(self.worker.status, Worker.Status.OFFLINE)

    def test_operator_poll_reconnects_offline_workers_and_preserves_drain(self):
        from django.utils import timezone
        from modelanvil.jobs.setup import observe_operator_worker, connection_state
        Worker.all_objects.filter(pk=self.worker.pk).update(status=Worker.Status.OFFLINE,
            last_heartbeat_at=timezone.now()-timezone.timedelta(minutes=2))
        self.worker.refresh_from_db()
        self.assertEqual(connection_state(self.worker), 'offline')
        observe_operator_worker(self.worker)
        self.assertEqual(self.worker.status, Worker.Status.AVAILABLE)
        self.assertIsNotNone(self.worker.last_heartbeat_at)
        Worker.all_objects.filter(pk=self.worker.pk).update(status=Worker.Status.DRAINING)
        observe_operator_worker(self.worker)
        self.assertEqual(self.worker.status, Worker.Status.DRAINING)

    def test_executor_exception_is_committed_as_failed_attempt(self):
        spec = importlib.util.find_spec("modelanvil.jobs.executor")
        self.assertIsNotNone(spec, "controlled worker executor module is missing")
        execute_one = importlib.import_module("modelanvil.jobs.executor").execute_one

        def executor(_descriptor, _context):
            raise RuntimeError("fixture execution failed")

        outcome = execute_one(self.worker, executor)

        self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "failed"})
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        attempt = JobAttempt.objects.get(job=self.job)
        self.assertEqual(self.job.status, Job.Status.FAILED)
        self.assertEqual(self.worker.slots, 1)
        self.assertEqual(attempt.status, JobAttempt.Status.FAILED)
        self.assertIn("fixture execution failed", attempt.error)

    def test_cooperative_cancel_stops_success_commit_and_releases_slot(self):
        execute_one = importlib.import_module("modelanvil.jobs.executor").execute_one
        observed = {}

        def executor(_descriptor, context):
            Job.all_objects.filter(pk=self.job.pk).update(
                desired_action=Job.DesiredAction.CANCEL,
            )
            observed["continue"] = context.heartbeat(progress=0.75)
            return None

        outcome = execute_one(self.worker, executor)

        self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "interrupted"})
        self.assertFalse(observed["continue"])
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        attempt = JobAttempt.objects.get(job=self.job)
        self.assertEqual(self.job.status, Job.Status.CANCELLED)
        self.assertEqual(self.worker.slots, 1)
        self.assertEqual(attempt.status, JobAttempt.Status.INTERRUPTED)
        self.assertIsNone(attempt.result_envelope)

    def test_execute_claim_runs_only_the_already_claimed_job(self):
        next_job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="next task",
            requirements={"accelerator": "cpu"},
        )
        descriptor = claim_job(self.worker, self.job)
        self.assertIsNotNone(descriptor)
        execute_claim = getattr(
            importlib.import_module("modelanvil.jobs.executor"), "execute_claim", None
        )
        self.assertTrue(callable(execute_claim), "claimed execution entry point is missing")

        outcome = execute_claim(self.worker, descriptor, command_fixture_executor)

        self.assertEqual(outcome["status"], "succeeded")
        self.job.refresh_from_db()
        next_job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.SUCCEEDED)
        self.assertEqual(next_job.status, Job.Status.QUEUED)
        self.assertEqual(JobAttempt.objects.filter(job=self.job).count(), 1)
        self.assertFalse(JobAttempt.objects.filter(job=next_job).exists())
