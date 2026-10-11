import io

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.identity.management.commands.bootstrap_dev import DEV_API_KEY
from modelanvil.identity.models import ApiKey, Membership, Project, Role, Team, Tenant, User
from modelanvil.runners.models import ModelVersion, TrainingRun


class BootstrapDevTests(TestCase):
    def test_bootstrap_is_idempotent_and_authenticates_an_empty_workspace(self):
        for _ in range(2):
            call_command("bootstrap_dev", stdout=io.StringIO())

        tenant = Tenant.objects.get(slug="default")
        user = User.objects.get(email="admin@modelanvil.local")
        self.assertEqual(Team.all_objects.filter(tenant_id=tenant.pk).count(), 1)
        project = Project.all_objects.get(tenant_id=tenant.pk)
        self.assertEqual(ApiKey.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(Membership.objects.get(tenant=tenant, user=user).role, Role.OWNER)
        self.assertEqual(Artifact.all_objects.count(), 0)
        self.assertEqual(ModelVersion.all_objects.count(), 0)
        self.assertEqual(TrainingRun.all_objects.count(), 0)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {DEV_API_KEY}")
        response = client.get("/api/v1/projects/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], str(project.pk))
