"""Create local development identity and an empty project, idempotently.

Populated demo screens live in Storybook. This command never fabricates
training evidence, upstream datasets, qualified models or serving deployments.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from modelanvil.identity.models import ApiKey, Membership, Project, Role, Team, Tenant, User, hash_api_key

DEV_API_KEY = "mkv_dev_master_key_for_local_testing_12345"


class Command(BaseCommand):
    help = "Create a local tenant, project, admin user and development API key."

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Tenant
        tenant, created_tenant = Tenant.objects.get_or_create(
            slug="default",
            defaults={"name": "Default Organization"},
        )
        tid = tenant.tenant_id
        if created_tenant:
            self.stdout.write(self.style.SUCCESS(f"Created default tenant: {tenant.name} ({tid})"))
        else:
            self.stdout.write(f"Default tenant active: {tenant.name} ({tid})")

        # 1b. Team & Project
        team, created_team = Team.objects.get_or_create(
            tenant_id=tid,
            slug="core-ai",
            defaults={"name": "Core AI Engineering", "description": "Core foundation and alignment team."},
        )
        project, created_project = Project.objects.get_or_create(
            tenant_id=tid,
            team=team,
            slug="primary-llm",
            defaults={"name": "Primary Foundation Model", "description": "Main model pre-training, fine-tuning, and alignment project."},
        )
        if created_project:
            self.stdout.write(self.style.SUCCESS(f"Created default project: {project.name} ({project.id})"))

        # 2. User
        user, created_user = User.objects.get_or_create(
            email="admin@modelanvil.local",
            defaults={"name": "Platform Administrator", "is_staff": True, "is_superuser": True},
        )
        if created_user:
            user.set_password("admin12345")
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created admin user: {user.email}"))

        # 3. Membership
        membership, created_mem = Membership.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults={"role": Role.OWNER},
        )
        if created_mem:
            self.stdout.write(self.style.SUCCESS(f"Granted OWNER role to {user.email} in {tenant.name}"))

        # 4. API Key
        secret_hash = hash_api_key(DEV_API_KEY)
        key, created_key = ApiKey.objects.get_or_create(
            tenant=tenant,
            name="local-dev-master-key",
            defaults={
                "secret_hash": secret_hash,
                "role": Role.OWNER,
                "created_by": user,
            },
        )
        if not created_key and (key.secret_hash != secret_hash or key.role != Role.OWNER):
            key.secret_hash = secret_hash
            key.role = Role.OWNER
            key.save()
        self.stdout.write(f"Local dev API key active: {DEV_API_KEY}")

        self.stdout.write(self.style.SUCCESS("Local development workspace is ready. Use Storybook for populated demo screens."))
