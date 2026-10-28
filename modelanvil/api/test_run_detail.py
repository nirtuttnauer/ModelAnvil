"""Run-detail projection checks: linkage, honesty and tenant isolation."""
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool
from modelanvil.runners.models import (
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
    TrainingCheckpoint,
    TrainingRun,
)


@override_settings(ALLOWED_HOSTS=["testserver"])
class RunDetailProjectionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.one = Tenant.objects.create(slug="run-one", name="One")
        self.two = Tenant.objects.create(slug="run-two", name="Two")
        self.auth_one = {"HTTP_AUTHORIZATION": f"Bearer {self.make_key(self.one)}"}
        self.auth_two = {"HTTP_AUTHORIZATION": f"Bearer {self.make_key(self.two)}"}

        self.pool = WorkerPool.objects.create(tenant_id=self.one.tenant_id, name="cpu", queue_name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.one.tenant_id, name="cpu-1", pool=self.pool, slots=2
        )
        self.policy = BudgetPolicy.objects.create(
            tenant_id=self.one.tenant_id, name="steps", period="monthly",
            unit="training_steps", limit_amount=100,
        )
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.one.tenant_id, name="char-tok", vocabulary_size=128
        )
        self.model = Model.objects.create(tenant_id=self.one.tenant_id, name="base")
        self.base_model_version = ModelVersion.objects.create(
            tenant_id=self.one.tenant_id, model=self.model, revision_no=1,
            tokenizer=self.tokenizer, architecture_ref="cpu-character-sft",
        )
        self.suite = EvaluationSuite.objects.create(tenant_id=self.one.tenant_id, name="smoke")
        self.suite_version = EvaluationSuiteVersion.objects.create(
            tenant_id=self.one.tenant_id, suite=self.suite, revision_no=1, cases_count=3
        )

    @staticmethod
    def make_key(tenant):
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name="test", role=Role.OWNER, secret_hash=digest)
        return secret

    def make_job(self, *, status=Job.Status.RUNNING, desired=Job.DesiredAction.CANCEL, name="linked job"):
        job = Job.objects.create(
            tenant_id=self.one.tenant_id, pool=self.pool, name=name,
            payload={"type": "qualified_training", "run_id": "seed"}, status=status,
            desired_action=desired,
        )
        BudgetReservation.objects.create(
            tenant_id=self.one.tenant_id, policy=self.policy, job_id=job.job_id,
            estimated_amount=10, period_start=timezone.localdate(),
        )
        return job

    def make_training_run(self, job):
        run = TrainingRun.objects.create(
            tenant_id=self.one.tenant_id, recipe_type=TrainingRun.RecipeType.FULL_SFT,
            base_model_version=self.base_model_version, tokenizer_version=self.tokenizer,
            pool=self.pool, job=job, status=TrainingRun.Status.RUNNING,
            total_steps=10, current_step=4,
            hardware_config={"execution_mode": "worker",
                             "pins": {"contract_digest": "contract-abc", "runtime": "cpu-character-sft"}},
            metrics_log=[{"step": 4, "loss": 0.5, "sample_id": "s"}],
        )
        TrainingCheckpoint.objects.create(
            tenant_id=self.one.tenant_id, training_run=run, step=4, state_digest="d" * 64,
            weights_manifest={"pins": {"contract_digest": "contract-abc"}, "weights_sha256": "a" * 64},
        )
        return run

    def test_unknown_kind_and_foreign_tenant_runs_are_not_disclosed(self):
        job = self.make_job()
        self.make_training_run(job)
        foreign = Job.objects.create(
            tenant_id=self.two.tenant_id,
            pool=WorkerPool.objects.create(tenant_id=self.two.tenant_id, name="other"),
            name="hidden",
        )
        response = self.client.get(f"/api/v1/run-details/job/{job.job_id}/", **self.auth_one)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.get(f"/api/v1/run-details/unknown/{job.job_id}/", **self.auth_one).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/run-details/job/{foreign.job_id}/", **self.auth_one).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/run-details/job/{job.job_id}/", **self.auth_two).status_code, 404)

    def test_training_detail_separates_observed_and_desired_and_links_the_job(self):
        job = self.make_job()
        run = self.make_training_run(job)
        response = self.client.get(f"/api/v1/run-details/training/{run.run_id}/", **self.auth_one)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()

        self.assertEqual(body["kind"], "training")
        self.assertEqual(body["observed"]["state"], "running")
        self.assertEqual(body["observed"]["current_step"], 4)
        self.assertEqual(body["desired"]["action"], "cancel")
        self.assertFalse(body["desired"]["acknowledged"])
        self.assertTrue(body["actions"]["cancel"]["requested"])
        self.assertFalse(body["actions"]["cancel"]["acknowledged"])
        self.assertEqual(body["links"]["job"], str(job.job_id))
        self.assertEqual(body["links"]["tokenizer_version"], str(self.tokenizer.tokenizer_id))
        self.assertEqual(body["inputs"]["runtime_contract"], "contract-abc")
        self.assertEqual(body["checkpoints"]["total"], 1)
        self.assertTrue(body["checkpoints"]["resume_candidate"]["available"])
        self.assertEqual(body["usage"]["reservations"][0]["state"], BudgetReservation.State.RESERVED)
        self.assertIn("generated_at", body)

    def test_unknown_ownership_and_lost_lease_are_explicit(self):
        job = self.make_job(desired=Job.DesiredAction.RUN)
        unknown = self.client.get(f"/api/v1/run-details/job/{job.job_id}/", **self.auth_one).json()
        self.assertEqual(unknown["ownership"]["state"], "unknown")
        self.assertIn("unknown", unknown["ownership"]["reason"])

        job.claimed_by = self.worker
        job.lease_expires_at = timezone.now() - timezone.timedelta(seconds=5)
        job.save(update_fields=["claimed_by", "lease_expires_at", "updated_at"])
        lost = self.client.get(f"/api/v1/run-details/job/{job.job_id}/", **self.auth_one).json()
        self.assertEqual(lost["ownership"]["state"], "lost")
        self.assertEqual(lost["ownership"]["worker"], "cpu-1")

    def test_attempts_are_paged_for_the_linked_job_only(self):
        job = self.make_job()
        self.make_training_run(job)
        other = self.make_job(name="unrelated")
        for index in range(3):
            JobAttempt.objects.create(
                tenant_id=self.one.tenant_id, job=job, worker=self.worker,
                fencing_token=f"token-{index}", status=JobAttempt.Status.FAILED,
                error="worker crashed", progress=0.4,
            )
        JobAttempt.objects.create(
            tenant_id=self.one.tenant_id, job=other, worker=self.worker,
            fencing_token="other-token", status=JobAttempt.Status.RUNNING,
        )
        run = TrainingRun.objects.get(job=job)
        response = self.client.get(f"/api/v1/run-details/training/{run.run_id}/attempts/", **self.auth_one)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["results"]
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["job_id"] for row in rows}, {str(job.job_id)})
        self.assertTrue(all(row["error"] == "worker crashed" for row in rows))

        job_response = self.client.get(f"/api/v1/run-details/job/{job.job_id}/attempts/", **self.auth_one)
        self.assertEqual(len(job_response.json()["results"]), 3)
        self.assertEqual(self.client.get(f"/api/v1/run-details/training/{run.run_id}/attempts/", **self.auth_two).status_code, 404)

    def test_long_attempt_history_pages_with_a_cursor_the_client_accepts(self):
        job = self.make_job()
        run = self.make_training_run(job)
        for index in range(60):
            JobAttempt.objects.create(
                tenant_id=self.one.tenant_id, job=job, worker=self.worker,
                fencing_token=f"long-{index}", status=JobAttempt.Status.EXPIRED,
            )
        page = self.client.get(f"/api/v1/run-details/job/{job.job_id}/attempts/", **self.auth_one).json()
        self.assertEqual(len(page["results"]), 50)
        self.assertIn("/api/v1/run-details/job/%s/attempts/" % job.job_id, page["next"])
        self.assertIn("cursor=", page["next"])

        cursor = page["next"].split("cursor=")[1]
        following = self.client.get(
            f"/api/v1/run-details/job/{job.job_id}/attempts/?cursor={cursor}", **self.auth_one
        ).json()
        self.assertEqual(len(following["results"]), 10)
        self.assertIsNone(following["next"])
        self.assertEqual(
            len({row["attempt_id"] for row in [*page["results"], *following["results"]]}), 60
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/run-details/job/{job.job_id}/attempts/?job_id={job.job_id}", **self.auth_one
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/run-details/training/{run.run_id}/attempts/", **self.auth_one
            ).json()["results"],
            self.client.get(
                f"/api/v1/run-details/job/{job.job_id}/attempts/", **self.auth_one
            ).json()["results"],
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/run-details/training/{run.run_id}/attempts/?cursor=not-a-cursor",
                **self.auth_one,
            ).status_code,
            404,
        )

    def test_resume_reports_the_blocker_instead_of_claiming_recovery(self):
        job = self.make_job(status=Job.Status.FAILED, desired=Job.DesiredAction.RUN)
        run = self.make_training_run(job)
        reservation = BudgetReservation.objects.get(job_id=job.job_id)
        reservation.state = BudgetReservation.State.SETTLED
        reservation.settled_amount = 4
        reservation.save(update_fields=["state", "settled_amount", "updated_at"])
        run.resource_reservation_id = reservation.reservation_id
        run.status = TrainingRun.Status.FAILED
        run.save(update_fields=["resource_reservation_id", "status", "updated_at"])

        body = self.client.get(f"/api/v1/run-details/training/{run.run_id}/", **self.auth_one).json()
        resume = body["actions"]["resume"]
        self.assertFalse(resume["available"])
        self.assertTrue(resume["checkpoint"]["available"])
        self.assertFalse(resume["budget"]["reservable"])
        self.assertEqual(resume["budget"]["state"], BudgetReservation.State.SETTLED)
        self.assertTrue(resume["permission"]["satisfied"])
        self.assertTrue(any("CPU character and CPU transformer" in reason for reason in resume["blocked_by"]))
        self.assertIn("immutable", resume["preserves_history"])

    def test_evaluation_detail_links_its_candidate_model(self):
        run = EvaluationRun.objects.create(
            tenant_id=self.one.tenant_id, suite_version=self.suite_version,
            candidate_model_version=self.base_model_version,
        )
        body = self.client.get(f"/api/v1/run-details/evaluation/{run.run_id}/", **self.auth_one).json()
        self.assertEqual(body["kind"], "evaluation")
        self.assertEqual(body["links"]["model_version"], str(self.base_model_version.model_version_id))
        self.assertEqual(body["inputs"]["suite_name"], "smoke")
        self.assertEqual(body["ownership"]["state"], "not_applicable")
        self.assertIn("level", body["evidence"])
        self.assertEqual(
            self.client.get(f"/api/v1/run-details/evaluation/{run.run_id}/attempts/", **self.auth_one).status_code,
            404,
        )