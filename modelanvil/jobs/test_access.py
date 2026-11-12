"""Jobs inherit access from their owning runs."""

from django.test import TestCase

from modelanvil.core.tenancy import reset_context, set_active_project, set_active_tenant
from modelanvil.identity.models import Project, Team, Tenant
from modelanvil.jobs.access import accessible_jobs
from modelanvil.jobs.models import Job, WorkerPool
from modelanvil.runners.models import (
    AlignmentRun,
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
    TrainingRun,
)


class AccessibleJobsTests(TestCase):
    def setUp(self):
        reset_context()
        self.addCleanup(reset_context)
        self.tenant = Tenant.objects.create(slug="job-access", name="Job Access")
        self.team = Team.all_objects.create(
            tenant_id=self.tenant.tenant_id, slug="lab", name="Lab",
        )
        self.caller = Project.all_objects.create(
            tenant_id=self.tenant.tenant_id, team=self.team, slug="caller", name="Caller",
        )
        self.other = Project.all_objects.create(
            tenant_id=self.tenant.tenant_id, team=self.team, slug="other", name="Other",
        )
        self.pool = WorkerPool.all_objects.create(
            tenant_id=self.tenant.tenant_id, name="cpu",
        )
        self.tokenizer = TokenizerVersion.all_objects.create(
            tenant_id=self.tenant.tenant_id, project=self.caller, name="tokenizer",
        )
        self.model = Model.all_objects.create(
            tenant_id=self.tenant.tenant_id, project=self.caller, name="policy",
        )
        self.version = ModelVersion.all_objects.create(
            tenant_id=self.tenant.tenant_id,
            project=self.caller,
            model=self.model,
            tokenizer=self.tokenizer,
            architecture_ref="fixture",
        )

    def _job(self, name):
        return Job.all_objects.create(
            tenant_id=self.tenant.tenant_id, project=self.caller, pool=self.pool, name=name,
        )

    def _as_caller(self):
        set_active_tenant(self.tenant.tenant_id)
        set_active_project(self.caller.id)

    def _visible_ids(self):
        self._as_caller()
        return set(accessible_jobs().values_list("pk", flat=True))

    def test_no_active_tenant_returns_no_jobs(self):
        job = self._job("stored")
        reset_context()

        found = accessible_jobs()

        self.assertTrue(Job.all_objects.filter(pk=job.pk).exists())
        self.assertEqual(list(found), [])
        self.assertFalse(found.exists())

    def test_hidden_training_run_job_is_omitted_and_accessible_jobs_remain(self):
        hidden = self._job("hidden-training")
        visible = self._job("visible")
        owned = self._job("owned-training")
        TrainingRun.all_objects.create(
            tenant_id=self.tenant.tenant_id,
            project=self.other,
            recipe_type=TrainingRun.RecipeType.FULL_SFT,
            tokenizer_version=self.tokenizer,
            pool=self.pool,
            job=hidden,
        )
        TrainingRun.all_objects.create(
            tenant_id=self.tenant.tenant_id,
            project=self.caller,
            recipe_type=TrainingRun.RecipeType.FULL_SFT,
            tokenizer_version=self.tokenizer,
            pool=self.pool,
            job=owned,
        )

        visible_ids = self._visible_ids()

        self.assertNotIn(hidden.pk, visible_ids)
        self.assertIn(visible.pk, visible_ids)
        self.assertIn(owned.pk, visible_ids)

    def test_hidden_evaluation_run_job_is_omitted(self):
        hidden = self._job("hidden-evaluation")
        visible = self._job("visible-evaluation")
        suite = EvaluationSuite.all_objects.create(
            tenant_id=self.tenant.tenant_id, project=self.other, name="suite",
        )
        suite_version = EvaluationSuiteVersion.all_objects.create(
            tenant_id=self.tenant.tenant_id, project=self.other, suite=suite,
        )
        EvaluationRun.all_objects.create(
            tenant_id=self.tenant.tenant_id,
            project=self.other,
            suite_version=suite_version,
            candidate_model_version=self.version,
            job=hidden,
        )

        visible_ids = self._visible_ids()

        self.assertNotIn(hidden.pk, visible_ids)
        self.assertIn(visible.pk, visible_ids)

    def test_hidden_alignment_run_job_is_omitted(self):
        hidden = self._job("hidden-alignment")
        visible = self._job("visible-alignment")
        AlignmentRun.all_objects.create(
            tenant_id=self.tenant.tenant_id,
            project=self.other,
            algorithm=AlignmentRun.Algorithm.DPO,
            policy_model_version=self.version,
            job=hidden,
        )

        visible_ids = self._visible_ids()

        self.assertNotIn(hidden.pk, visible_ids)
        self.assertIn(visible.pk, visible_ids)
