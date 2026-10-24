"""Receipt integrity tests using storage fixtures; these do not claim measured training work."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from modelanvil.identity.models import Tenant, Team, Project
from modelanvil.jobs.models import Job, JobAttempt, WorkerPool, Worker
from modelanvil.runners.models import (AlignmentRun, AlignmentCheckpoint, AlignmentStageAttempt,
    Model, ModelVersion, TokenizerVersion)


class StageReceiptTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(slug='stage-receipts', name='Storage fixtures')
        self.tenant = tenant.pk
        team = Team.objects.create(tenant_id=self.tenant, slug='team', name='Team')
        project = Project.objects.create(tenant_id=self.tenant, team=team, slug='project', name='Project')
        pool = WorkerPool.objects.create(tenant_id=self.tenant, name='CPU')
        worker = Worker.objects.create(tenant_id=self.tenant, pool=pool, name='Worker')
        job = Job.objects.create(tenant_id=self.tenant, project=project, pool=pool, name='Storage fixture')
        self.attempt = JobAttempt.objects.create(tenant_id=self.tenant, job=job, worker=worker, fencing_token='storage-fixture')
        tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant, project=project, name='Storage fixture')
        model = Model.objects.create(tenant_id=self.tenant, project=project, name='Storage fixture')
        version = ModelVersion.objects.create(tenant_id=self.tenant, project=project, model=model,
            tokenizer=tokenizer, revision_no=1, architecture_ref='storage-fixture')
        self.run = AlignmentRun.objects.create(tenant_id=self.tenant, project=project, worker_pool=pool,
            job=job, algorithm='reward_model', policy_model_version=version, total_steps=3)
        self.units = {'training_steps': 1, 'generated_tokens': 0, 'alignment_scores': 2}

    def receipt(self, **changes):
        fields = {'tenant_id': self.tenant, 'alignment_run': self.run, 'job_attempt': self.attempt,
            'sequence': 1, 'phase': 'reward_update', 'input_digest': 'a' * 64, 'upper_units': self.units}
        return AlignmentStageAttempt(**{**fields, **changes})

    def checkpoint(self):
        return AlignmentCheckpoint.objects.create(tenant_id=self.tenant, alignment_run=self.run,
            step=1, state_digest='b' * 64, policy_state={'fixture': True})

    def test_lost_work_keeps_explicit_unknown_actuals_and_immutable_bounds(self):
        receipt = self.receipt(); receipt.save()
        self.assertIsNone(receipt.actual_units)
        receipt.status = 'uncertain'; receipt.observations = {'measurement': 'unknown'}; receipt.save()
        receipt.refresh_from_db(); self.assertIsNone(receipt.actual_units)
        receipt.actual_units = {key: 0 for key in self.units}
        with self.assertRaisesRegex(ValueError, 'immutable'): receipt.save()
        receipt.actual_units = None; receipt.upper_units = {**self.units, 'training_steps': 2}
        with self.assertRaisesRegex(ValueError, 'immutable'): receipt.save()

    def test_measured_stage_requires_owning_checkpoint_and_cannot_rebill(self):
        receipt = self.receipt(); receipt.save()
        receipt.status, receipt.actual_units = 'committed', self.units
        with self.assertRaises(ValidationError): receipt.save()
        receipt.checkpoint = self.checkpoint(); receipt.save()
        receipt.actual_units = {**self.units, 'alignment_scores': 1}
        with self.assertRaisesRegex(ValueError, 'immutable'): receipt.save()

    def test_counts_scope_and_unavailable_evaluation_fail_closed(self):
        for changes in ({'actual_units': self.units}, {'upper_units': {**self.units, 'training_steps': True}},
                {'upper_units': {**self.units, 'alignment_scores': -1}}, {'sequence': 302}, {'input_digest': 'invalid'}):
            with self.assertRaises(ValidationError): self.receipt(**changes).save()
        receipt = self.receipt(status='unavailable', phase='evaluation', checkpoint=self.checkpoint())
        receipt.save(); self.assertIsNone(receipt.actual_units)
        self.assertIsNotNone(receipt.checkpoint_id)
        other = self.receipt(sequence=2, status='committed', actual_units=self.units, checkpoint=receipt.checkpoint)
        with self.assertRaises(ValidationError): other.save()
