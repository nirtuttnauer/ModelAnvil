"""Identity models: Tenant, User, Membership, Role, ApiKey.

Tenancy is the root of authorization. A :class:`User` belongs to one or
more :class:`Tenant` via :class:`Membership`, each carrying a
:class:`Role`. API keys are scoped to a single tenant and grant the key
holder a fixed role. The authentication layer resolves the active tenant
from the principal and applies RBAC.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from typing import Any, Optional

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel
from modelanvil.core.tenancy import get_active_project, get_active_tenant

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    ENGINEER = "engineer", "Engineer"
    REVIEWER = "reviewer", "Reviewer"
    VIEWER = "viewer", "Viewer"
    WORKER = "worker", "Worker"


#: Capability -> minimum role. RBAC decisions compare the caller's role
#: against the required minimum using this ordering.
ROLE_RANK: dict[str, int] = {
    Role.OWNER: 100,
    Role.ADMIN: 80,
    Role.MANAGER: 60,
    Role.ENGINEER: 40,
    Role.REVIEWER: 30,
    Role.VIEWER: 20,
    Role.WORKER: 10,
}


def role_at_least(role: Optional[str], required: str) -> bool:
    """Return True if ``role`` is at least as privileged as ``required``."""
    if role is None:
        return False
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(required, 0)


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
class Tenant(models.Model):
    """A single-tenant organization boundary.

    Every tenant-scoped row in the platform carries a ``tenant_id`` that
    references one of these. Tenants are hard-isolated: no query, API
    response, or artifact path may cross tenant boundaries.
    """

    tenant_id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16,
        choices=[("active", "active"), ("suspended", "suspended"), ("deleted", "deleted")],
        default="active",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"

    def is_active(self) -> bool:
        return self.status == "active"


# ---------------------------------------------------------------------------
# User manager
# ---------------------------------------------------------------------------
class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: Optional[str], **extra_fields: Any) -> "User":
        if not email:
            raise ValueError("The email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: Optional[str] = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: Optional[str] = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(AbstractBaseUser, PermissionsMixin):
    """A platform user, identified by email."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._role_cache: dict[uuid.UUID, Optional[str]] = {}

    def get_full_name(self) -> str:
        return self.name or self.email

    def get_short_name(self) -> str:
        return self.name or self.email

    def role_in(self, tenant_id: uuid.UUID) -> Optional[str]:
        """Return the user's highest-role in a tenant, or None."""
        if tenant_id in self._role_cache:
            return self._role_cache[tenant_id]
        membership = (
            Membership.objects.filter(user=self, tenant_id=tenant_id).order_by("-role_rank").first()
        )
        role: Optional[str] = membership.role if membership else None
        self._role_cache[tenant_id] = role
        return role

    def has_role_in(self, tenant_id: uuid.UUID, required: str) -> bool:
        """Return True if the user's role in ``tenant_id`` >= ``required``."""
        return role_at_least(self.role_in(tenant_id), required)

    def __str__(self) -> str:
        return self.email


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------
class Membership(models.Model):
    """A user's role within a tenant."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    role_rank = models.PositiveSmallIntegerField(default=20)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("tenant", "user")
        ordering = ("-role_rank",)\


    def save(self, *args: Any, **kwargs: Any) -> None:
        self.role_rank = ROLE_RANK.get(self.role, 0)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user_id} in {self.tenant_id} as {self.role}"


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------
class ApiKey(models.Model):
    """A bearer credential scoped to one tenant and one role, optionally bound to a project.

    Only the SHA-256 hash of the secret is stored; the plaintext secret is
    shown exactly once at creation. The key grants its holder a fixed role
    within the owning tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    project = models.ForeignKey(
        "Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="api_keys"
    )
    name = models.CharField(max_length=200)
    secret_hash = models.CharField(max_length=64, unique=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.ENGINEER)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_api_keys"
    )
    last_used_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)

    def clean(self) -> None:
        if self.project_id and self.project.tenant_id != self.tenant_id:
            raise ValidationError("Project must belong to the API key's tenant.")

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


def hash_api_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Return ``(plaintext_secret, secret_hash)`` for a new API key."""
    secret = "mkv_" + secrets.token_urlsafe(32)
    return secret, hash_api_key(secret)


# ---------------------------------------------------------------------------
# Teams and projects (WP-02 organization hierarchy)
#
# The organization is a tenant. Inside it, work is structured as
# team -> project. Teams and projects are tenant-scoped
# (:class:`~modelanvil.core.models.TenantContextModel`), so the auto-scoping
# manager guarantees a key can only ever see its own tenant's hierarchy.
# Memberships carry an explicit role grant at the team or project level.
# ---------------------------------------------------------------------------
class Team(TenantContextModel):
    """A team within a tenant, grouping members and projects."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "slug"), name="team_tenant_slug_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class Project(TenantContextModel):
    """A project within a tenant, owned by a team.

    A project is the unit of work for goals, datasets, and runs. It must
    share a tenant with its owning team.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="projects")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "slug"), name="project_tenant_slug_uniq"),
        ]

    def clean(self) -> None:
        if self.team_id and self.tenant_id and self.team.tenant_id and self.team.tenant_id != self.tenant_id:
            raise ValidationError("Project and team must share the same tenant.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.tenant_id:
            self.tenant_id = get_active_tenant()
        if self.team_id:
            team = Team.all_objects.filter(pk=self.team_id).first()
            if team is None:
                raise ValueError("Project team does not exist.")
            if team.tenant_id != self.tenant_id:
                raise ValueError("Project and team must share the same tenant.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class TeamMembership(TenantContextModel):
    """A user's role grant within a team."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    role_rank = models.PositiveSmallIntegerField(default=20)

    class Meta:
        unique_together = ("team", "user")
        ordering = ("-role_rank",)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.role_rank = ROLE_RANK.get(self.role, 0)
        if not self.tenant_id:
            self.tenant_id = get_active_tenant()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user_id} in team {self.team_id} as {self.role}"


class ProjectMembership(TenantContextModel):
    """A user's explicit role grant within a project."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    role_rank = models.PositiveSmallIntegerField(default=20)

    class Meta:
        unique_together = ("project", "user")
        ordering = ("-role_rank",)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.role_rank = ROLE_RANK.get(self.role, 0)
        if not self.tenant_id:
            self.tenant_id = get_active_tenant()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user_id} in project {self.project_id} as {self.role}"


class ProjectConfig(TenantContextModel):
    """An immutable, versioned revision of a project's goals.

    Revisions are append-only and numbered monotonically per project. The
    highest ``revision_no`` is the project's active configuration; older
    revisions are retained for audit and rollback. ``created_by`` records the
    API key that submitted the revision (the API surface is key-first, so
    there is no end-user identity to attribute).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="configs")
    revision_no = models.PositiveIntegerField()
    goals = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "ApiKey", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        unique_together = ("project", "revision_no")
        ordering = ("project", "-revision_no")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.tenant_id:
            self.tenant_id = get_active_tenant()
        super().save(*args, **kwargs)

    @classmethod
    def current(cls, project, *, tenant_id: Optional[uuid.UUID] = None):
        """Return the latest revision for ``project`` (the active config)."""
        queryset = cls.all_objects.filter(project=project)
        if tenant_id is not None:
            queryset = queryset.filter(tenant_id=tenant_id)
        return queryset.order_by("-revision_no").first()

    def __str__(self) -> str:
        return f"config {self.project_id} rev {self.revision_no}"


# ---------------------------------------------------------------------------
# Cross-Project Resource Grants
# ---------------------------------------------------------------------------
class ProjectGrant(TenantContextModel):
    """An explicit grant allowing a target project to access resources owned by another project within the same tenant."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="granted_resources")
    granted_to_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="received_grants")
    resource_type = models.CharField(max_length=64, default="all")  # model, tokenizer, data_source, etc.
    resource_id = models.UUIDField(null=True, blank=True)  # None = all resources of resource_type in project
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "project", "granted_to_project", "resource_type", "resource_id"),
                name="project_grant_uniq",
            )
        ]

    def clean(self) -> None:
        if self.project_id and self.granted_to_project_id:
            if self.project.tenant_id != self.tenant_id or self.granted_to_project.tenant_id != self.tenant_id:
                raise ValidationError("Grants cannot cross tenant boundaries.")
            if self.project_id == self.granted_to_project_id:
                raise ValidationError("Cannot grant a project access to itself.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.tenant_id:
            self.tenant_id = self.project.tenant_id if self.project_id else get_active_tenant()
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Grant from {self.project_id} to {self.granted_to_project_id} for {self.resource_type}:{self.resource_id}"


def _model_uuid_field_name(model_cls: Any) -> str:
    fields = [field for field in model_cls._meta.concrete_fields
              if isinstance(field, models.UUIDField) and field.name != "tenant_id"]
    for field in fields:
        if field.primary_key:
            return field.name
    if fields:
        return fields[0].name
    return "pk"


def check_resource_access(
    resource: Any,
    project_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
) -> bool:
    """Check if a resource is accessible in the given tenant and project context."""
    if tenant_id is None:
        tenant_id = get_active_tenant()
    if resource is None:
        return False

    # 1. Hard tenant boundary check
    res_tenant_id = getattr(resource, "tenant_id", None)
    if res_tenant_id is not None and tenant_id is not None and str(res_tenant_id) != str(tenant_id):
        return False

    # 2. Project boundary check
    if project_id is None:
        project_id = get_active_project()

    # If caller has no project constraint (e.g. tenant-wide admin/key), access is permitted
    if project_id is None:
        return True

    res_project_id = getattr(resource, "project_id", None)
    # If resource has no project assigned, it is tenant-wide and accessible
    if res_project_id is None:
        return True

    # Same project
    if str(res_project_id) == str(project_id):
        return True

    # Cross-project: check for an explicit ProjectGrant
    model_name = resource._meta.model_name
    uuid_field = _model_uuid_field_name(resource.__class__)
    uuid_val = getattr(resource, uuid_field, getattr(resource, "pk", None))
    return ProjectGrant.objects.filter(
        tenant_id=tenant_id,
        project_id=res_project_id,
        granted_to_project_id=project_id,
    ).filter(
        models.Q(resource_type="all")
        | models.Q(resource_type=model_name, resource_id__isnull=True)
        | models.Q(resource_type=model_name, resource_id=uuid_val)
    ).exists()


def get_accessible_queryset(
    model_cls: Any,
    project_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
):
    """Return a queryset for model_cls scoped to the tenant and project context (including ProjectGrants)."""
    if tenant_id is None:
        tenant_id = get_active_tenant()
    if tenant_id is None:
        return model_cls.objects.none()

    qs = model_cls.objects.filter(tenant_id=tenant_id)
    if not hasattr(model_cls, "project"):
        return qs

    if project_id is None:
        project_id = get_active_project()

    if project_id is None:
        return qs

    uuid_field = _model_uuid_field_name(model_cls)

    granted_project_ids = ProjectGrant.objects.filter(
        tenant_id=tenant_id,
        granted_to_project_id=project_id,
        resource_id__isnull=True,
    ).filter(
        models.Q(resource_type="all") | models.Q(resource_type=model_cls._meta.model_name)
    ).values_list("project_id", flat=True)

    granted_resource_uuids = ProjectGrant.objects.filter(
        tenant_id=tenant_id,
        granted_to_project_id=project_id,
        resource_id__isnull=False,
    ).filter(
        models.Q(resource_type="all") | models.Q(resource_type=model_cls._meta.model_name)
    ).values_list("resource_id", flat=True)

    filters = (
        models.Q(project_id=project_id)
        | models.Q(project__isnull=True)
        | models.Q(project_id__in=granted_project_ids)
    )
    if granted_resource_uuids:
        filters = filters | models.Q(**{f"{uuid_field}__in": granted_resource_uuids})

    return qs.filter(filters)


class AccountAction(models.Model):
    """One-time password reset or teammate invitation. Only the secret hash is stored."""

    class Purpose(models.TextChoices):
        PASSWORD_RESET = 'password_reset', 'Password reset'
        INVITATION = 'invitation', 'Invitation'

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    email = models.EmailField()
    secret_hash = models.CharField(max_length=64, unique=True)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.CASCADE, related_name='account_actions')
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='account_actions')
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.ENGINEER)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=['purpose', 'email'], name='identity_ac_purpose_d3dbfd_idx')]
