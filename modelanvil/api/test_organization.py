"""Organization API regressions (WP-02 tenancy and hierarchy).\n\nCovers the organization surface mounted at ``/api/v1/``: cross-tenant\nisolation of reads/mutations, explicit role-grant RBAC through API keys,\nstructural validation on teams/projects, project-config immutability,\nand membership lifecycle. Existing behavior is preserved; this file only\nadds test coverage and does not modify any other module.\n"""
from __future__ import annotations

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.identity.models import (
    ApiKey,
    Membership,
    Project,
    ProjectConfig,
    Team,
    TeamMembership,
    Tenant,
    User,
    generate_api_key,
)


def _api_key(tenant: "Tenant", role: str, name: str = "") -> dict[str, str]:
    """Create a tenant-scoped API key and return its HTTP auth header."""
    secret, digest = generate_api_key()
    ApiKey.objects.create(
        tenant=tenant, name=name or f"test-{role}", role=role, secret_hash=digest,
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {secret}"}


@override_settings(ALLOWED_HOSTS=["testserver"])
class OrganizationIsolationTests(TestCase):
    """Two organizations cannot list/read/mutate each other's resources via API."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant_a = Tenant.objects.create(slug="org-a", name="Org A")
        self.tenant_b = Tenant.objects.create(slug="org-b", name="Org B")
        self.key_a = _api_key(self.tenant_a, "owner")
        self.key_b = _api_key(self.tenant_b, "owner")

        # Parallel hierarchies in both tenants. The identical team slug across
        # tenants is deliberate: uniqueness must be per-tenant, not global.
        user_b = User.objects.create(email="member-b@example.com", name="Member B")
        self.team_a = Team.objects.create(
            slug="eng", name="Eng A", tenant_id=self.tenant_a.tenant_id,
        )
        self.team_b = Team.objects.create(
            slug="eng", name="Eng B", tenant_id=self.tenant_b.tenant_id,
        )
        self.project_a = Project.objects.create(
            team=self.team_a, slug="proj-a", name="Project A",
            tenant_id=self.tenant_a.tenant_id,
        )
        self.project_b = Project.objects.create(
            team=self.team_b, slug="proj-b", name="Project B",
            tenant_id=self.tenant_b.tenant_id,
        )
        self.membership_b = Membership.objects.create(
            tenant=self.tenant_b, user=user_b, role="viewer",
        )

    def test_list_scopes_to_owning_tenant(self) -> None:
        response = self.client.get("/api/v1/teams/", **self.key_a)
        self.assertEqual(response.status_code, 200, response.content)
        ids = {item["id"] for item in response.json()["results"]}
        self.assertEqual(ids, {str(self.team_a.id)})

        response = self.client.get("/api/v1/projects/", **self.key_b)
        self.assertEqual(response.status_code, 200, response.content)
        ids = {item["id"] for item in response.json()["results"]}
        self.assertEqual(ids, {str(self.project_b.id)})

    def test_retrieve_foreign_resource_is_invisible(self) -> None:
        foreign_urls = (
            f"/api/v1/teams/{self.team_b.id}/",
            f"/api/v1/projects/{self.project_b.id}/",
            f"/api/v1/memberships/{self.membership_b.id}/",
        )
        for url in foreign_urls:
            response = self.client.get(url, **self.key_a)
            self.assertEqual(response.status_code, 404, f"{url}: {response.content}")

    def test_mutations_cannot_target_foreign_resources(self) -> None:
        payload = {"team": str(self.team_b.id), "user": "victim@example.com", "role": "viewer"}
        response = self.client.post(
            "/api/v1/team-memberships/", data=payload, format="json", **self.key_a,
        )
        self.assertEqual(response.status_code, 404, response.content)

        payload = {"project": str(self.project_b.id), "goals": {}}
        response = self.client.post(
            "/api/v1/project-configs/", data=payload, format="json", **self.key_a,
        )
        self.assertEqual(response.status_code, 404, response.content)

    def test_slug_uniqueness_is_per_tenant(self) -> None:
        # The identical "eng" slug exists in both tenants from setUp, proving
        # the per-tenant constraint did not reject cross-tenant reuse.
        self.assertEqual(Team.objects.filter(slug="eng").count(), 2)

        # A brand-new tenant may reuse any existing slug; only its own
        # duplicates are rejected.
        tenant_c = Tenant.objects.create(slug="org-c", name="Org C")
        key_c = _api_key(tenant_c, "owner")
        response = self.client.post(
            "/api/v1/teams/", data={"slug": "eng", "name": "Eng C"}, format="json", **key_c,
        )
        self.assertEqual(response.status_code, 201, response.content)

        # A duplicate inside the caller's own tenant is rejected.
        response = self.client.post(
            "/api/v1/teams/", data={"slug": "eng", "name": "Dup"}, format="json", **self.key_a,
        )
        body = response.json()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(body["error"]["code"], "conflict")


@override_settings(ALLOWED_HOSTS=["testserver"])
class OrganizationRoleEnforcementTests(TestCase):
    """API keys enforce the explicit role grants declared by the viewsets."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.tenant = Tenant.objects.create(slug="org-rbac", name="Org RBAC")
        self.owner_key = _api_key(self.tenant, "owner")
        self.manager_key = _api_key(self.tenant, "manager")
        self.viewer_key = _api_key(self.tenant, "viewer")
        self.team = Team.objects.create(
            slug="rbac", name="RBAC Team", tenant_id=self.tenant.tenant_id,
        )

    def test_viewer_cannot_create_organization_resources(self) -> None:
        response = self.client.post(
            "/api/v1/teams/", data={"slug": "new", "name": "New"}, format="json", **self.viewer_key,
        )
        self.assertEqual(response.status_code, 403, response.content)

        response = self.client.post(
            "/api/v1/projects/",
            data={"team": str(self.team.id), "slug": "new-proj", "name": "P"},
            format="json", **self.viewer_key,
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_viewer_cannot_grant_roles(self) -> None:
        user = User.objects.create(email="member@example.com")
        grant = TeamMembership.objects.create(
            team=self.team, user=user, role="viewer", tenant_id=self.tenant.tenant_id,
        )
        response = self.client.put(
            f"/api/v1/team-memberships/{grant.id}/",
            data={"role": "manager"}, format="json", **self.viewer_key,
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_manager_can_grant_roles_up_to_own(self) -> None:
        user = User.objects.create(email="member2@example.com")
        grant = TeamMembership.objects.create(
            team=self.team, user=user, role="viewer", tenant_id=self.tenant.tenant_id,
        )
        response = self.client.put(
            f"/api/v1/team-memberships/{grant.id}/",
            data={"role": "engineer"}, format="json", **self.manager_key,
        )
        self.assertEqual(response.status_code, 200, response.content)
        grant.refresh_from_db()
        self.assertEqual(grant.role, "engineer")

    def test_cannot_grant_role_above_own(self) -> None:
        user = User.objects.create(email="member3@example.com")
        grant = TeamMembership.objects.create(
            team=self.team, user=user, role="viewer", tenant_id=self.tenant.tenant_id,
        )
        response = self.client.put(
            f"/api/v1/team-memberships/{grant.id}/",
            data={"role": "owner"}, format="json", **self.manager_key,
        )
        body = response.json()
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(body["error"]["code"], "forbidden")

    def test_team_deletion_requires_admin(self) -> None:
        response = self.client.delete(f"/api/v1/teams/{self.team.id}/", **self.manager_key)
        self.assertEqual(response.status_code, 403, response.content)

    def test_admin_deletion_blocks_teams_with_projects(self) -> None:
        Project.objects.create(
            team=self.team, slug="kept-proj", name="Kept", tenant_id=self.tenant.tenant_id,
        )
        response = self.client.delete(f"/api/v1/teams/{self.team.id}/", **self.owner_key)
        body = response.json()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(body["error"]["code"], "conflict")

    def test_user_removal_removes_membership_not_user(self) -> None:
        user = User.objects.create(email="departing@example.com")
        Membership.objects.create(tenant=self.tenant, user=user, role="viewer")
        response = self.client.delete(f"/api/v1/users/{user.id}/", **self.owner_key)
        self.assertEqual(response.status_code, 204, response.content)
        self.assertTrue(User.objects.filter(id=user.id).exists())
        self.assertFalse(Membership.objects.filter(tenant=self.tenant, user=user).exists())

    def test_config_revisions_are_append_only(self) -> None:
        project = Project.objects.create(
            team=self.team, slug="cfg-proj", name="Cfg", tenant_id=self.tenant.tenant_id,
        )
        for goals in ({"objective": "one"}, {"objective": "two"}):
            response = self.client.post(
                "/api/v1/project-configs/",
                data={"project": str(project.id), "goals": goals},
                format="json", **self.manager_key,
            )
            self.assertEqual(response.status_code, 201, response.content)

        listing = self.client.get(
            f"/api/v1/project-configs/?project={project.id}", **self.manager_key
        ).json()["results"]
        self.assertEqual(len(listing), 2)
        # Newest revision first; the earlier one is untouched.
        self.assertEqual(int(listing[0]["revision_no"]), 2)
        self.assertEqual(int(listing[1]["revision_no"]), 1)
        self.assertEqual(listing[1]["goals"], {"objective": "one"})

    def test_config_revisions_are_immutable_via_api(self) -> None:
        project = Project.objects.create(
            team=self.team, slug="cfg2-proj", name="Cfg2", tenant_id=self.tenant.tenant_id,
        )
        response = self.client.post(
            "/api/v1/project-configs/",
            data={"project": str(project.id), "goals": {"objective": "x"}},
            format="json", **self.manager_key,
        )
        config_id = response.json()["id"]
        for method in ("put", "delete"):
            caller = getattr(self.client, method)
            response = caller(
                f"/api/v1/project-configs/{config_id}/", **self.manager_key,
            )
            self.assertEqual(response.status_code, 405, response.content)
