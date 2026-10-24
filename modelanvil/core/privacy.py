"""Network policy for shipped acquisition transports; no external content processing."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from urllib.parse import urlsplit
import urllib.request

from django.conf import settings

from modelanvil.core.tenancy import get_active_project, get_active_tenant

_scope = ContextVar('acquisition_privacy_scope', default=None)


class PrivacyRefused(ValueError):
    pass


def origin(url):
    try:
        if not isinstance(url, str):
            raise ValueError()
        parsed = urlsplit(url)
        if (parsed.username or parsed.password or not parsed.hostname or parsed.fragment
                or parsed.scheme not in ('https', 'http')):
            raise ValueError()
        if parsed.scheme != 'https' and not (settings.DEBUG and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError()
        host = parsed.hostname.lower()
        if ':' in host:
            host = f'[{host}]'
        port = parsed.port
        standard = 443 if parsed.scheme == 'https' else 80
        return f'{parsed.scheme}://{host}' + (f':{port}' if port and port != standard else '')
    except (TypeError, ValueError):
        raise PrivacyRefused('Acquisition requires HTTPS without embedded credentials. Use scoped credentials instead.') from None


def project_policy(tenant, project):
    from modelanvil.core.models import ProjectPrivacyPolicy
    policy = ProjectPrivacyPolicy.all_objects.filter(tenant_id=tenant, project_id=project).first() if tenant and project else None
    installed = list(settings.MODELANVIL_ACQUISITION_ORIGINS)
    from modelanvil.runners.external_inference import installed_targets
    providers = installed_targets(tenant, project)
    from modelanvil.runners.mcp_connections import installed_targets as installed_mcp
    mcp = installed_mcp(tenant, project)
    allowed_mcp = [v for v in (policy.mcp_targets if policy else []) if v in {m['id'] for m in mcp if m['available']}]
    allowed = [value for value in (policy.external_generation_targets if policy else []) if value in {p['id'] for p in providers}]
    return {'offline': settings.MODELANVIL_OFFLINE or bool(policy and policy.offline),
        'acquisition_origins': [v for v in (policy.acquisition_origins if policy else installed) if v in installed],
        'installation_origins': installed,
        'measurement_retention_days': policy.measurement_retention_days if policy else 30,
        'external_judges': False, 'external_generation': bool(allowed) and not (settings.MODELANVIL_OFFLINE or bool(policy and policy.offline)),
        'external_generation_targets': allowed, 'installed_generation_targets': providers, 'external_analytics': False,
        'mcp_targets': allowed_mcp, 'installed_mcp_targets': mcp, 'code_execution': bool(policy and policy.code_execution),
        'support_upload': False, 'diagnostic_content_collection': False,
        'product_history_retention': 'Retained until explicitly deleted through the authorized product APIs.'}


@contextmanager
def acquisition_scope(tenant, project, *, public_provisioning=False):
    token = _scope.set((tenant, project, public_provisioning))
    try:
        yield
    finally:
        _scope.reset(token)


def require_destination(url, *, purpose='acquisition'):
    if purpose != 'acquisition':
        raise PrivacyRefused('External judges, generation, analytics and support uploads are not supported. Use local processing.')
    scope = _scope.get()
    tenant, project, public = scope if scope is not None else (get_active_tenant(), get_active_project(), False)
    policy = project_policy(tenant, project)
    if policy['offline']:
        raise PrivacyRefused('This installation or project is offline. Use provisioned local files or ask its administrator to review Privacy settings.')
    if public and not settings.MODELANVIL_PUBLIC_MODEL_DOWNLOADS:
        raise PrivacyRefused('Bundled-model downloads require the installation owner to enable MODELANVIL_PUBLIC_MODEL_DOWNLOADS after reviewing the Hugging Face destinations. Provision local files to stay offline.')
    destination = origin(url)
    if destination not in policy['acquisition_origins']:
        raise PrivacyRefused(f'Acquisition destination {destination} is not allowed. Ask the installation owner to review it and the project administrator to approve it in Privacy settings.')
    return destination


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_destination(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and origin(req.full_url) != origin(newurl):
            redirected.headers = {k: v for k, v in redirected.headers.items()
                if k.lower() in ('accept', 'accept-encoding', 'range', 'if-range', 'user-agent')}
            redirected.unredirected_hdrs = {}
        return redirected


def open_acquisition(request, *, timeout):
    if request.get_method() not in ('GET', 'HEAD') or request.data:
        raise PrivacyRefused('Acquisition can only read approved sources; content uploads are disabled.')
    require_destination(request.full_url)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects()).open(request, timeout=timeout)


def guarded_session():
    """Use the optional runtime's requests dependency; do not add it to the CPU install."""
    import requests

    class AcquisitionSession(requests.Session):
        def send(self, request, **kwargs):
            if request.method not in ('GET', 'HEAD') or request.body:
                raise PrivacyRefused('Acquisition may only read approved sources; private content uploads are disabled.')
            if _scope.get() is None and not (get_active_tenant() and get_active_project()):
                raise PrivacyRefused('Acquisition needs an explicit workspace or provisioning scope; unscoped SDK requests are refused.')
            self.cookies.clear()
            request.headers.pop('Cookie', None)
            require_destination(request.url)
            return super().send(request, **kwargs)

        def rebuild_auth(self, prepared_request, response):
            super().rebuild_auth(prepared_request, response)
            if origin(prepared_request.url) != origin(response.request.url):
                for key in list(prepared_request.headers):
                    if key.lower() not in ('accept', 'accept-encoding', 'range', 'if-range', 'user-agent', 'connection'):
                        prepared_request.headers.pop(key)

    session = AcquisitionSession()
    session.trust_env = False  # No ambient proxy, netrc credentials or cookies across projects.
    return session


@lru_cache(maxsize=1)
def install_hub_guard():
    from huggingface_hub import set_client_factory, constants
    # Native Xet downloads use another HTTP stack; keep this qualified path on guarded HTTP.
    constants.HF_HUB_DISABLE_XET = True
    constants.HF_HUB_DISABLE_TELEMETRY = True
    set_client_factory(guarded_hub_client)


def guarded_hub_client():
    """Guard every request and redirect in the pinned Hub 1.x HTTP transport."""
    import httpx

    def check(request):
        if request.method not in ('GET', 'HEAD') or request.read():
            raise PrivacyRefused('Acquisition may only read approved sources; private content uploads are disabled.')
        if _scope.get() is None and not (get_active_tenant() and get_active_project()):
            raise PrivacyRefused('Acquisition needs an explicit workspace or provisioning scope; unscoped SDK requests are refused.')
        request.headers.pop('Cookie', None)
        require_destination(str(request.url))

    class AcquisitionClient(httpx.Client):
        def _build_redirect_request(self, request, response):
            redirected = super()._build_redirect_request(request, response)
            if origin(str(request.url)) != origin(str(redirected.url)):
                for key in list(redirected.headers):
                    if key.lower() not in ('accept', 'accept-encoding', 'range', 'if-range', 'user-agent', 'connection', 'host'):
                        redirected.headers.pop(key)
            return redirected

    return AcquisitionClient(trust_env=False, follow_redirects=True, timeout=None,
                             event_hooks={'request': [check]})
