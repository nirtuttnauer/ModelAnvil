"""Self-service local accounts using CSRF-protected HttpOnly browser credentials."""
from datetime import timedelta
import uuid

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as PasswordError
from django.db import IntegrityError, transaction
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from modelanvil.identity.models import ApiKey, Membership, Project, Role, Team, Tenant, User, generate_api_key, hash_api_key

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
    response = Response({'token': 'session', 'name': user.name, 'organization': str(membership.tenant_id)})
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
        authenticated = bool(key and Membership.objects.filter(tenant_id=key.tenant_id, user_id=key.created_by_id).exists())
        response = Response({'signup_enabled': settings.MODELANVIL_SELF_SERVICE_ACCOUNTS, 'authenticated': authenticated})
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


class AccountSignOut(APIView):
    def post(self, request):
        if getattr(request, 'modelanvil_cookie_auth', False):
            request.auth.is_active = False
            request.auth.save(update_fields=['is_active'])
        response = Response(status=204)
        response.delete_cookie(COOKIE, path='/api/v1/', samesite='Lax')
        return response
