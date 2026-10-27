"""Self-service local accounts using CSRF-protected HttpOnly browser credentials."""
from datetime import timedelta
import secrets
import uuid

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as PasswordError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import (
    AccountAction, ApiKey, Membership, Project, Role, Team, Tenant, User, generate_api_key, hash_api_key,
)

COOKIE = 'modelanvil_session'


class AccountInput(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(trim_whitespace=False, min_length=1, max_length=256, write_only=True)
    name = serializers.CharField(max_length=100, required=False)


def browser_session(request, user, membership):
    secret, hashed = generate_api_key()
    ApiKey.objects.create(tenant=membership.tenant, role=membership.role, created_by=user,
                          name='Browser session', secret_hash=hashed, expires_at=timezone.now() + timedelta(hours=24))
    rotate_token(request)
    response = Response({'token': 'session', 'name': user.name, 'organization': str(membership.tenant_id), 'role': membership.role})
    response.set_cookie(COOKIE, secret, max_age=86400, httponly=True, secure=not settings.DEBUG,
                        samesite='Lax', path='/api/v1/')
    response['Cache-Control'] = 'no-store'
    return response


@method_decorator(ensure_csrf_cookie, name='dispatch')
class AccountStatus(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        secret = request.COOKIES.get(COOKIE, '')
        key = ApiKey.objects.filter(secret_hash=hash_api_key(secret), is_active=True, expires_at__gt=timezone.now(),
            tenant__status='active', created_by__is_active=True).first() if secret else None
        membership = Membership.objects.filter(tenant_id=key.tenant_id, user_id=key.created_by_id).first() if key else None
        authenticated = bool(membership)
        from modelanvil.core.pilot_gate import commercial_status
        response = Response({'signup_enabled': settings.MODELANVIL_SELF_SERVICE_ACCOUNTS, 'authenticated': authenticated,
            'role': membership.role if membership else None, 'can_invite': bool(membership and membership.role == Role.OWNER),
            'email': key.created_by.email if membership else None, **commercial_status()})
        response['Cache-Control'] = 'no-store'
        return response


@method_decorator(csrf_protect, name='dispatch')
class AccountSignUp(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'accounts'

    def post(self, request):
        if not settings.MODELANVIL_SELF_SERVICE_ACCOUNTS:
            return Response({'detail': 'Account creation is disabled on this installation. Sign in or request access from its owner.'}, status=403)
        serializer = AccountInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if len(data['password']) < 10:
            raise serializers.ValidationError({'password': 'Use at least 10 characters.'})
        user = User(email=data['email'].lower(), name=data.get('name') or 'My workspace')
        try:
            validate_password(data['password'], user)
        except PasswordError as exc:
            raise serializers.ValidationError({'password': exc.messages}) from None
        try:
            with transaction.atomic():
                user.set_password(data['password'])
                user.save()
                tenant = Tenant.objects.create(slug=f'workspace-{uuid.uuid4().hex}', name=f'{user.name} workspace')
                membership = Membership.objects.create(tenant=tenant, user=user, role=Role.OWNER)
                team = Team.objects.create(tenant_id=tenant.pk, name='My team', slug='my-team')
                Project.objects.create(tenant_id=tenant.pk, team=team, name='My first fine-tune', slug='first-fine-tune')
                return browser_session(request, user, membership)
        except IntegrityError:
            raise serializers.ValidationError('An account already uses this email. Sign in instead.') from None


@method_decorator(csrf_protect, name='dispatch')
class AccountSignIn(AccountSignUp):
    def post(self, request):
        serializer = AccountInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = authenticate(request, username=data['email'].lower(), password=data['password'])
        membership = Membership.objects.filter(user=user, tenant__status='active').order_by('-role_rank').first() if user else None
        if not user or not membership:
            return Response({'detail': 'Email or password is incorrect, or workspace access is unavailable.'}, status=401)
        return browser_session(request, user, membership)


def issue_action(purpose, email, *, tenant=None, project=None, role=Role.ENGINEER, hours=1):
    secret = secrets.token_urlsafe(24)
    prior = AccountAction.objects.filter(purpose=purpose, email=email.lower(), used_at__isnull=True)
    if purpose == AccountAction.Purpose.INVITATION:
        prior = prior.filter(tenant=tenant)
    prior.update(revoked_at=timezone.now())
    AccountAction.objects.create(purpose=purpose, email=email.lower(), secret_hash=hash_api_key(secret),
        tenant=tenant, project=project, role=role, expires_at=timezone.now() + timedelta(hours=hours))
    return secret


def open_action(purpose, email, secret):
    action = AccountAction.objects.filter(purpose=purpose, email=email.lower(), secret_hash=hash_api_key(secret),
        used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
    if action is None:
        raise serializers.ValidationError('That code is invalid or expired. Request a new one.')
    return action


def consume_action(action):
    now = timezone.now()
    if AccountAction.objects.filter(pk=action.pk, used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now).update(used_at=now) != 1:
        raise serializers.ValidationError('That code is invalid or expired. Request a new one.')


def apply_password(user, password):
    if len(password) < 10:
        raise serializers.ValidationError({'password': 'Use at least 10 characters.'})
    try:
        validate_password(password, user)
    except PasswordError as exc:
        raise serializers.ValidationError({'password': exc.messages}) from None
    user.set_password(password)
    if user.pk:
        user.save(update_fields=['password'])


@method_decorator(csrf_protect, name='dispatch')
class AccountPasswordReset(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'accounts'

    def post(self, request):
        email = serializers.EmailField().run_validation(request.data.get('email', '')).lower()
        user = User.objects.filter(email=email, is_active=True).first()
        code = issue_action(AccountAction.Purpose.PASSWORD_RESET, email, hours=1) if user else None
        payload = {'status': 'ok'}
        if settings.MODELANVIL_SEND_RESET_EMAIL and settings.EMAIL_HOST:
            if code:
                try:
                    send_mail(
                        'ModelAnvil password reset',
                        f'Your ModelAnvil reset code is {code}. It expires in one hour. If you did not request this, ignore this message.',
                        getattr(settings, 'DEFAULT_FROM_EMAIL', 'root@localhost'),
                        [email],
                        fail_silently=False,
                    )
                except Exception:
                    code = None
            payload['delivery'] = 'If this address has an account, reset instructions were emailed.'
        elif code and settings.DEBUG:
            payload['reset_code'] = code
            payload['delivery'] = 'This installation has no email delivery. Use the reset code below.'
        else:
            payload['delivery'] = 'Email delivery is not configured on this installation.'
        return Response(payload)


@method_decorator(csrf_protect, name='dispatch')
class AccountPasswordResetConfirm(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'accounts'

    @transaction.atomic
    def post(self, request):
        email = serializers.EmailField().run_validation(request.data.get('email', '')).lower()
        password = serializers.CharField(trim_whitespace=False, min_length=1, max_length=256).run_validation(request.data.get('password', ''))
        secret = serializers.CharField(trim_whitespace=False, min_length=8, max_length=128).run_validation(request.data.get('code', ''))
        action = open_action(AccountAction.Purpose.PASSWORD_RESET, email, secret)
        user = User.objects.filter(email=email, is_active=True).first()
        membership = Membership.objects.filter(user=user, tenant__status='active').order_by('-role_rank').first() if user else None
        if not user or not membership:
            raise serializers.ValidationError('That code is invalid or expired. Request a new one.')
        consume_action(action)
        apply_password(user, password)
        ApiKey.objects.filter(created_by=user, is_active=True).update(is_active=False)
        return browser_session(request, user, membership)


class AccountInvite(APIView):
    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [permissions.IsAuthenticated, TenantRBAC]
    required_role = Role.OWNER
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'accounts'

    def get(self, request):
        tenant = get_active_tenant()
        invitations = AccountAction.objects.filter(tenant_id=tenant, purpose=AccountAction.Purpose.INVITATION).order_by('-created_at')[:20]
        members = Membership.objects.filter(tenant_id=tenant).select_related('user').order_by('-role_rank')
        now = timezone.now()
        response = Response({'invitations': [{'id': str(a.pk), 'email': a.email, 'role': a.role,
            'expires_at': a.expires_at, 'status': 'revoked' if a.revoked_at else 'accepted' if a.used_at else 'expired' if a.expires_at <= now else 'pending'} for a in invitations],
            'members': [{'id': str(m.pk), 'email': m.user.email, 'role': m.role} for m in members]})
        response['Cache-Control'] = 'no-store'
        return response

    @transaction.atomic
    def post(self, request):
        email = serializers.EmailField().run_validation(request.data.get('email', '')).lower()
        tenant_id = get_active_tenant()
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        project_id = get_active_project()
        project = Project.objects.filter(pk=project_id, tenant_id=tenant_id).first() if project_id else Project.objects.filter(tenant_id=tenant_id).order_by('created_at').first()
        if project is None:
            raise serializers.ValidationError('Create a project before inviting a teammate.')
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('That email already has a workspace account.')
        if Membership.objects.filter(tenant_id=tenant_id).exclude(role=Role.OWNER).exists() or AccountAction.objects.filter(
                purpose=AccountAction.Purpose.INVITATION, tenant_id=tenant_id, used_at__isnull=True,
                revoked_at__isnull=True, expires_at__gt=timezone.now()).exists():
            raise serializers.ValidationError('This workspace already has a teammate or pending invitation. Revoke an unused invitation before creating another.')
        code = issue_action(AccountAction.Purpose.INVITATION, email, tenant=tenant, project=project, role=Role.REVIEWER, hours=72)
        response = Response({'email': email, 'invite_code': code, 'role': Role.REVIEWER,
            'delivery': 'Share this one-time code privately. The reviewer can inspect workspace evidence and submit reviews, without launching jobs or managing access.',
            'expires_in_hours': 72}, status=201)
        response['Cache-Control'] = 'no-store'
        return response

    @transaction.atomic
    def delete(self, request, invitation_id):
        Tenant.objects.select_for_update().get(pk=get_active_tenant())
        action = AccountAction.objects.filter(pk=invitation_id, tenant_id=get_active_tenant(), purpose=AccountAction.Purpose.INVITATION).first()
        if action is None:
            return Response(status=404)
        if action.used_at:
            raise serializers.ValidationError('This invitation was accepted. Remove the membership to revoke access.')
        action.revoked_at = timezone.now()
        action.save(update_fields=['revoked_at'])
        return Response(status=204)


class AccountInviteRevoke(AccountInvite):
    http_method_names = ["delete", "options"]


class AccountAccess(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        response = Response({'role': request.modelanvil_role})
        response['Cache-Control'] = 'no-store'
        return response


@method_decorator(csrf_protect, name='dispatch')
class AccountInviteAccept(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'accounts'

    def post(self, request):
        email = serializers.EmailField().run_validation(request.data.get('email', '')).lower()
        name = serializers.CharField(max_length=100, required=False).run_validation(request.data.get('name') or 'Teammate')
        password = serializers.CharField(trim_whitespace=False, min_length=1, max_length=256).run_validation(request.data.get('password', ''))
        secret = serializers.CharField(trim_whitespace=False, min_length=8, max_length=128).run_validation(request.data.get('code', ''))
        action = open_action(AccountAction.Purpose.INVITATION, email, secret)
        if not action.tenant_id or not action.tenant.is_active() or action.role not in (Role.REVIEWER, Role.ENGINEER):
            raise serializers.ValidationError('That invitation is no longer available.')
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=action.tenant_id)
                consume_action(action)
                user = User(email=email, name=name or 'Teammate')
                apply_password(user, password)
                user.save()
                membership = Membership.objects.create(tenant=action.tenant, user=user, role=Role.REVIEWER)
        except IntegrityError:
            raise serializers.ValidationError('That email already has an account.') from None
        return browser_session(request, user, membership)


class AccountSignOut(APIView):
    def post(self, request):
        if getattr(request, 'modelanvil_cookie_auth', False):
            request.auth.is_active = False
            request.auth.save(update_fields=['is_active'])
        response = Response(status=204)
        response.delete_cookie(COOKIE, path='/api/v1/', samesite='Lax')
        return response
