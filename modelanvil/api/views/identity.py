"""Identity REST API (WP-02).

Tenant, user, membership, and API-key management. Every endpoint is scoped
to the request's *active tenant* — the tenant the bearer API key belongs to —
so a key can only ever read or mutate its own tenant. Authorization is
enforced by :class:`modelanvil.identity.auth.TenantRBAC` against the key's
fixed role.

The API is API-key-first: ``request.user`` is the authenticated
:class:`~modelanvil.identity.models.ApiKey` (see
:class:`ApiKeyAuthentication`), and the active tenant is a UUID resolved from
that key. All querysets are manually scoped to the active tenant so no query
can cross a tenant boundary.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.db import IntegrityError, transaction
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import (
    ApiKey,
    Membership,
    Project,
    ProjectConfig,
    ProjectGrant,
    ProjectMembership,
    Role,
    Team,
    TeamMembership,
    Tenant,
    User,
    generate_api_key,
    role_at_least,
)


def remove_membership(membership):
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=membership.tenant_id)
        if membership.role == Role.OWNER:
            raise serializers.ValidationError('Owner access cannot be removed here.')
        ApiKey.objects.filter(tenant_id=membership.tenant_id, created_by_id=membership.user_id).update(is_active=False)
        membership.delete()


# ---------------------------------------------------------------------------
# Shared RBAC-aware ViewSet base
# ---------------------------------------------------------------------------
class _TenantRBACViewSet(viewsets.ModelViewSet):
    """A ModelViewSet gated by the active-tenant RBAC model.

    ``required_role`` is set per-request in :meth:`initial` from the action,
    *before* DRF runs the permission checks, so :class:`TenantRBAC` sees the
    role appropriate to the action (reads are cheap, writes are privileged).
    """

    permission_classes = [IsAuthenticated, TenantRBAC]
    _ACTION_ROLES: dict[str, str] = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.ADMIN,
        "update": Role.ADMIN,
        "partial_update": Role.ADMIN,
        "destroy": Role.ADMIN,
    }

    def initial(self, request, *args: object, **kwargs: object) -> None:
        self.required_role = self._ACTION_ROLES.get(self.action, Role.VIEWER)  # type: ignore[attr-defined]
        super().initial(request, *args, **kwargs)


def _active_tenant() -> Optional[uuid.UUID]:
    return get_active_tenant()


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------
class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ("tenant_id", "slug", "name", "status", "created_at", "updated_at")
        read_only_fields = fields


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
    """The active tenant.

    A bearer key is bound to exactly one tenant, so ``list``/``retrieve``
    only ever return that tenant. Tenants are not created/updated/deleted via
    the API-key surface (that is a platform/bootstrap operation).
    """

    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, TenantRBAC]
    required_role = Role.VIEWER
    lookup_field = "tenant_id"

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return Tenant.objects.none()
        return Tenant.objects.filter(tenant_id=tenant)


# ---------------------------------------------------------------------------
# Users (people who are members of the active tenant)
# ---------------------------------------------------------------------------
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "name", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class UserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices, default=Role.VIEWER)
    name = serializers.CharField(required=False, allow_blank=True, default="")


class UserViewSet(_TenantRBACViewSet):
    """Manage the people who belong to the active tenant.

    ``create`` adds a member (and their role); ``destroy`` removes the
    membership (never the user, who may belong to other tenants).
    """

    serializer_class = UserSerializer
    lookup_field = "id"

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return User.objects.none()
        member_ids = Membership.objects.filter(tenant_id=tenant).values_list("user_id", flat=True)
        return User.objects.filter(id__in=member_ids).order_by("email")

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = UserCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"]
        role = ser.validated_data["role"]
        with transaction.atomic():
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={"name": ser.validated_data.get("name") or email.split("@")[0]},
            )
            membership, created = Membership.objects.get_or_create(
                tenant_id=tenant, user=user, defaults={"role": role}
            )
            if not created and membership.role != role:
                membership.role = role
                membership.save(update_fields=["role", "role_rank"])
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        user = self.get_object()
        membership = Membership.objects.get(tenant_id=tenant, user_id=user.id)
        remove_membership(membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
class ApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiKey
        fields = ("id", "name", "role", "project", "last_used_at", "expires_at", "is_active", "created_at")
        read_only_fields = ("id", "last_used_at", "created_at")


class ApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    role = serializers.ChoiceField(choices=Role.choices, default=Role.ENGINEER)
    project = serializers.UUIDField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class ApiKeyViewSet(_TenantRBACViewSet):
    """Manage API keys for the active tenant.

    The plaintext secret is returned exactly once, on creation. ``destroy``
    revokes (deactivates) the key rather than deleting it, preserving the
    audit trail.
    """

    serializer_class = ApiKeySerializer
    lookup_field = "id"
    _ACTION_ROLES = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.ENGINEER,
        "destroy": Role.ADMIN,
    }

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return ApiKey.objects.none()
        return ApiKey.objects.filter(tenant_id=tenant).order_by("-created_at")

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = ApiKeyCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if not role_at_least(request.modelanvil_role, ser.validated_data["role"]):
            raise serializers.ValidationError({"role": "Cannot grant a role above your own."})
        secret, secret_hash = generate_api_key()
        project_id = ser.validated_data.get("project")
        if project_id:
            if not Project.objects.filter(tenant_id=tenant, id=project_id).exists():
                return Response(
                    {"error": {"code": "not_found", "message": "Project not found in this tenant."}},
                    status=status.HTTP_404_NOT_FOUND,
                )
        key = ApiKey.objects.create(
            tenant_id=tenant,
            project_id=project_id,
            name=ser.validated_data["name"],
            role=ser.validated_data["role"],
            secret_hash=secret_hash,
            expires_at=ser.validated_data.get("expires_at"),
            created_by=getattr(request.user, "created_by", None),
        )
        data = ApiKeySerializer(key).data
        data["secret"] = secret  # plaintext, shown exactly once
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: ApiKey) -> None:
        instance.is_active = False
        instance.save(update_fields=["is_active"])


# ---------------------------------------------------------------------------
# Memberships (role assignments within the active tenant)
# ---------------------------------------------------------------------------
class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Membership
        fields = ("id", "tenant_id", "user_id", "email", "role", "role_rank", "created_at")
        read_only_fields = ("id", "tenant_id", "user_id", "role_rank", "created_at")


class MembershipUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)


class MembershipViewSet(_TenantRBACViewSet):
    """Manage role assignments (memberships) in the active tenant.

    ``create``/``update`` set or change a member's role; ``destroy`` removes
    the membership.
    """

    serializer_class = MembershipSerializer
    lookup_field = "id"

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return Membership.objects.none()
        return (
            Membership.objects.filter(tenant_id=tenant)
            .select_related("user")
            .order_by("-role_rank")
        )

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = UserCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"]
        role = ser.validated_data["role"]
        with transaction.atomic():
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={"name": ser.validated_data.get("name") or email.split("@")[0]},
            )
            membership, created = Membership.objects.get_or_create(
                tenant_id=tenant, user=user, defaults={"role": role}
            )
            if not created and membership.role != role:
                membership.role = role
                membership.save(update_fields=["role", "role_rank"])
        return Response(
            MembershipSerializer(membership).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, *args: object, **kwargs: object) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = MembershipUpdateSerializer(data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        if "role" in ser.validated_data:
            # Never permit role escalation beyond the caller's own authority.
            requested_role = ser.validated_data["role"]
            caller_role = getattr(request, "modelanvil_role", None)
            if not role_at_least(caller_role, requested_role):
                return Response(
                    {"error": {"code": "forbidden", "message": "Cannot grant a role above your own."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            instance.role = requested_role
            instance.save()
        return Response(MembershipSerializer(instance).data)

    def destroy(self, request, *args: object, **kwargs: object) -> Response:
        remove_membership(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Teams (WP-02 organization hierarchy: tenant -> team -> project)
# ---------------------------------------------------------------------------
class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ("id", "slug", "name", "description", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class TeamCreateSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=64)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class TeamViewSet(_TenantRBACViewSet):
    """Teams in the active tenant.

    Reads are open to every tenant member; structural changes require
    MANAGER, deletion requires ADMIN.
    """

    serializer_class = TeamSerializer
    lookup_field = "id"
    _ACTION_ROLES = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.MANAGER,
        "update": Role.MANAGER,
        "partial_update": Role.MANAGER,
        "destroy": Role.ADMIN,
    }

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return Team.objects.none()
        return Team.objects.filter(tenant_id=tenant)

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = TeamCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if Team.objects.filter(tenant_id=tenant, slug=ser.validated_data["slug"]).exists():
            return Response(
                {"error": {"code": "conflict", "message": "A team with this slug already exists."}},
                status=status.HTTP_409_CONFLICT,
            )
        team = Team(tenant_id=tenant, **ser.validated_data)
        team.save()
        return Response(TeamSerializer(team).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args: object, **kwargs: object) -> Response:
        instance = self.get_object()
        if instance.projects.exists():
            return Response(
                {"error": {"code": "conflict", "message": "Team still has projects; remove them first."}},
                status=status.HTTP_409_CONFLICT,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class ProjectSerializer(serializers.ModelSerializer):
    team_slug = serializers.SlugField(source="team.slug", read_only=True)

    class Meta:
        model = Project
        fields = ("id", "team", "team_slug", "slug", "name", "description", "created_at", "updated_at")
        read_only_fields = ("id", "team_slug", "created_at", "updated_at")


class ProjectCreateSerializer(serializers.Serializer):
    team = serializers.UUIDField()
    slug = serializers.SlugField(max_length=64)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class ProjectViewSet(_TenantRBACViewSet):
    """Projects in the active tenant, each owned by a team in the same tenant."""

    serializer_class = ProjectSerializer
    lookup_field = "id"
    _ACTION_ROLES = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.MANAGER,
        "update": Role.MANAGER,
        "partial_update": Role.MANAGER,
        "destroy": Role.ADMIN,
    }

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return Project.objects.none()
        return Project.objects.filter(tenant_id=tenant).select_related("team")

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = ProjectCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        team = Team.objects.filter(tenant_id=tenant, pk=ser.validated_data["team"]).first()
        if team is None:
            return Response(
                {"error": {"code": "not_found", "message": "Team not found in this tenant."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        if Project.objects.filter(tenant_id=tenant, slug=ser.validated_data["slug"]).exists():
            return Response(
                {"error": {"code": "conflict", "message": "A project with this slug already exists."}},
                status=status.HTTP_409_CONFLICT,
            )
        project = Project(
            team=team,
            tenant_id=tenant,
            slug=ser.validated_data["slug"],
            name=ser.validated_data["name"],
            description=ser.validated_data["description"],
        )
        project.save()
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Team and project membership (explicit role grants)
# ---------------------------------------------------------------------------
class TeamMembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.CharField(source="user.name", read_only=True)

    class Meta:
        model = TeamMembership
        fields = ("id", "team", "email", "name", "role", "role_rank", "created_at")
        read_only_fields = ("id", "team", "email", "name", "role_rank", "created_at")


class TeamMembershipCreateSerializer(serializers.Serializer):
    team = serializers.UUIDField()
    user = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices, default=Role.VIEWER)
    name = serializers.CharField(required=False, allow_blank=True, default="")


class ProjectMembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.CharField(source="user.name", read_only=True)

    class Meta:
        model = ProjectMembership
        fields = ("id", "project", "email", "name", "role", "role_rank", "created_at")
        read_only_fields = ("id", "project", "email", "name", "role_rank", "created_at")


class ProjectMembershipCreateSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    user = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices, default=Role.VIEWER)
    name = serializers.CharField(required=False, allow_blank=True, default="")


class _RoleUpdateSerializer(serializers.Serializer):
    """Role-only update payload shared by the membership viewsets."""

    role = serializers.ChoiceField(choices=Role.choices)


class _MembershipGrantViewSet(_TenantRBACViewSet):
    """Shared behavior for team/project membership grants.

    Grants are explicit: ``create`` adds a user with a role, ``update``
    changes the role (never above the caller's own tenant role), and
    ``destroy`` removes the grant. Reads are open to every tenant member.
    """

    lookup_field = "id"
    _ACTION_ROLES = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.MANAGER,
        "update": Role.MANAGER,
        "partial_update": Role.MANAGER,
        "destroy": Role.MANAGER,
    }
    _owner_label = ""
    _owner_field = ""

    def _grant_model(self):
        raise NotImplementedError

    def _owner(self, ser_validated: dict, tenant):
        raise NotImplementedError

    def get_create_serializer(self, **kwargs):
        raise NotImplementedError

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = self.get_create_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        owner = self._owner(ser.validated_data, tenant)
        if owner is None:
            return Response(
                {"error": {"code": "not_found", "message": f"{self._owner_label} not found in this tenant."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        email = ser.validated_data["user"]
        role = ser.validated_data["role"]
        with transaction.atomic():
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={"name": ser.validated_data.get("name") or email.split("@")[0]},
            )
            membership, created = self._grant_model().objects.get_or_create(
                **{self._owner_field: owner},
                user=user,
                tenant_id=tenant,
                defaults={"role": role},
            )
            if not created and membership.role != role:
                membership.role = role
                membership.save(update_fields=["role", "role_rank"])
        return Response(self.get_serializer(membership).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args: object, **kwargs: object) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        ser = _RoleUpdateSerializer(data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        if "role" in ser.validated_data:
            # Never permit role escalation beyond the caller's own authority.
            requested_role = ser.validated_data["role"]
            caller_role = getattr(request, "modelanvil_role", None)
            if not role_at_least(caller_role, requested_role):
                return Response(
                    {"error": {"code": "forbidden", "message": "Cannot grant a role above your own."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            instance.role = requested_role
            instance.save()
        return Response(self.get_serializer(instance).data)

    def destroy(self, request, *args: object, **kwargs: object) -> Response:
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamMembershipViewSet(_MembershipGrantViewSet):
    """Role grants on teams in the active tenant."""

    serializer_class = TeamMembershipSerializer
    _owner_label = "Team"
    _owner_field = "team"

    def _grant_model(self):
        return TeamMembership

    def _owner(self, ser_validated: dict, tenant):
        return Team.objects.filter(tenant_id=tenant, pk=ser_validated["team"]).first()

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return TeamMembership.objects.none()
        queryset = TeamMembership.objects.filter(team__tenant_id=tenant).select_related("team", "user")
        team_id = self.request.query_params.get("team")
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        return queryset.order_by("-role_rank")

    def get_create_serializer(self, **kwargs):
        return TeamMembershipCreateSerializer(**kwargs)


class ProjectMembershipViewSet(_MembershipGrantViewSet):
    """Explicit role grants on projects in the active tenant."""

    serializer_class = ProjectMembershipSerializer
    _owner_label = "Project"
    _owner_field = "project"

    def _grant_model(self):
        return ProjectMembership

    def _owner(self, ser_validated: dict, tenant):
        return Project.objects.filter(tenant_id=tenant, pk=ser_validated["project"]).first()

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return ProjectMembership.objects.none()
        queryset = ProjectMembership.objects.filter(project__tenant_id=tenant).select_related("project", "user")
        project_id = self.request.query_params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset.order_by("-role_rank")

    def get_create_serializer(self, **kwargs):
        return ProjectMembershipCreateSerializer(**kwargs)


# ---------------------------------------------------------------------------
# Project configuration (versioned goals)
# ---------------------------------------------------------------------------
class ProjectConfigSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ProjectConfig
        fields = ("id", "project", "revision_no", "goals", "notes", "created_by_name", "created_at")
        read_only_fields = fields

    def get_created_by_name(self, obj: ProjectConfig):
        return obj.created_by.name if obj.created_by is not None else None


class ProjectConfigCreateSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    goals = serializers.DictField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ProjectConfigViewSet(_TenantRBACViewSet):
    """Versioned project goals.

    Revisions are immutable and append-only: ``create`` appends the next
    revision (``revision_no`` auto-increments per project). There is no
    update or delete — the highest revision is the active configuration and
    older revisions are retained for audit and rollback.
    """

    serializer_class = ProjectConfigSerializer
    lookup_field = "id"
    _ACTION_ROLES = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.MANAGER,
    }

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return ProjectConfig.objects.none()
        queryset = ProjectConfig.objects.filter(project__tenant_id=tenant).select_related("project", "created_by")
        project_id = self.request.query_params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset.order_by("project", "-revision_no")

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = ProjectConfigCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        project = Project.objects.filter(tenant_id=tenant, pk=ser.validated_data["project"]).first()
        if project is None:
            return Response(
                {"error": {"code": "not_found", "message": "Project not found in this tenant."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        for attempt in range(3):
            try:
                with transaction.atomic():
                    latest = (
                        ProjectConfig.objects.filter(project=project)
                        .order_by("-revision_no")
                        .values_list("revision_no", flat=True)
                        .first()
                    )
                    config = ProjectConfig(
                        project=project,
                        tenant_id=tenant,
                        revision_no=(latest or 0) + 1,
                        goals=ser.validated_data["goals"],
                        notes=ser.validated_data["notes"],
                        created_by=request.user,
                    )
                    config.save()
                return Response(ProjectConfigSerializer(config).data, status=status.HTTP_201_CREATED)
            except IntegrityError:
                # A concurrent create claimed the same revision number; retry
                # against the fresh maximum.
                if attempt == 2:
                    return Response(
                        {"error": {"code": "conflict", "message": "Concurrent config revision; retry the request."}},
                        status=status.HTTP_409_CONFLICT,
                    )
        return Response(
            {"error": {"code": "conflict", "message": "Concurrent config revision; retry the request."}},
            status=status.HTTP_409_CONFLICT,
        )

    def update(self, request, *args: object, **kwargs: object) -> Response:
        return Response(
            {"error": {"code": "method_not_allowed", "message": "Config revisions are immutable."}},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args: object, **kwargs: object) -> Response:
        return Response(
            {"error": {"code": "method_not_allowed", "message": "Config revisions are immutable."}},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


# ---------------------------------------------------------------------------
# Project grants (WP-02 cross-project resource access within tenant)
# ---------------------------------------------------------------------------
class ProjectGrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectGrant
        fields = ("id", "tenant_id", "project", "granted_to_project", "resource_type", "resource_id", "role")
        read_only_fields = ("id", "tenant_id")


class ProjectGrantCreateSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    granted_to_project = serializers.UUIDField()
    resource_type = serializers.CharField(required=False, default="all")
    resource_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    role = serializers.ChoiceField(choices=Role.choices, default=Role.VIEWER)


class ProjectGrantViewSet(_TenantRBACViewSet):
    """Manage cross-project resource grants within the active tenant."""

    serializer_class = ProjectGrantSerializer
    lookup_field = "id"
    _ACTION_ROLES = {
        "list": Role.VIEWER,
        "retrieve": Role.VIEWER,
        "create": Role.MANAGER,
        "update": Role.MANAGER,
        "partial_update": Role.MANAGER,
        "destroy": Role.MANAGER,
    }

    def get_queryset(self):
        tenant = _active_tenant()
        if tenant is None:
            return ProjectGrant.objects.none()
        return ProjectGrant.objects.filter(tenant_id=tenant).select_related("project", "granted_to_project")

    def create(self, request, *args: object, **kwargs: object) -> Response:
        tenant = _active_tenant()
        ser = ProjectGrantCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        owner_proj = Project.objects.filter(tenant_id=tenant, pk=ser.validated_data["project"]).first()
        target_proj = Project.objects.filter(tenant_id=tenant, pk=ser.validated_data["granted_to_project"]).first()
        if not owner_proj or not target_proj:
            return Response(
                {"error": {"code": "not_found", "message": "Project not found in this tenant."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        if owner_proj.id == target_proj.id:
            return Response(
                {"error": {"code": "bad_request", "message": "Cannot grant a project access to itself."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        grant, _ = ProjectGrant.objects.get_or_create(
            tenant_id=tenant,
            project=owner_proj,
            granted_to_project=target_proj,
            resource_type=ser.validated_data.get("resource_type", "all"),
            resource_id=ser.validated_data.get("resource_id"),
            defaults={"role": ser.validated_data.get("role", Role.VIEWER)},
        )
        return Response(ProjectGrantSerializer(grant).data, status=status.HTTP_201_CREATED)
