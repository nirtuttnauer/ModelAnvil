"""Operator-installed plugins. Requests select IDs, never Python modules or secrets."""
import hashlib
import importlib
import json
import os
import re

from django.conf import settings
from jsonschema import Draft202012Validator, ValidationError, SchemaError


class PluginError(ValueError):
    pass


# These ids stay deferred until a recorded human pilot asks for one provider.
# Runpod's control plane is already implemented and is the only expansion candidate.
DEFERRED_UNTIL_PILOT = frozenset({
    'runpod-serverless', 'vast', 'lambda', 'paperspace', 'coreweave', 'nebius', 'crusoe',
    'scaleway', 'aws', 'gce', 'azure', 'modal', 'together', 'fireworks',
    'huggingface-endpoints', 'baseten', 'replicate', 'customer-kubernetes', 'customer-slurm',
})


class ProviderError(Exception):
    def __init__(self, code="provider_unavailable", *, uncertain=True):
        self.code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else "provider_unavailable"
        self.uncertain = uncertain
        super().__init__(self.code)


def installed_plugins(tenant_id, kind=None):
    return {key: value for key, value in settings.MODELANVIL_PLUGINS.items()
            if str(tenant_id) in value.get("tenant_ids", []) and (kind is None or value.get("kind") == kind)}


def provider_claim(plugin_id):
    if plugin_id == 'runpod':
        return 'implemented_unqualified'
    if plugin_id in DEFERRED_UNTIL_PILOT:
        return 'deferred'
    return 'operator_installed'


def definition(plugin_id, tenant_id, kind):
    if not isinstance(plugin_id, str):
        raise PluginError("Invalid installed plugin ID.")
    if plugin_id in DEFERRED_UNTIL_PILOT:
        raise PluginError(f'{plugin_id} stays deferred until a recorded pilot asks for one provider.')
    entry = installed_plugins(tenant_id, kind).get(plugin_id)
    if entry is None:
        raise PluginError("Plugin is not installed for this tenant.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", plugin_id):
        raise PluginError("Invalid installed plugin ID.")
    if entry.get("contract_version") != "1.0" or "configuration_schema" not in entry:
        raise PluginError("Plugin must declare contract version 1.0 and its configuration schema.")
    digest = hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return entry, digest


def validate_configuration(schema, configuration):
    try:
        Draft202012Validator.check_schema(schema)
        # Configuration schemas are local documents, never network fetch requests.
        def reject_refs(value):
            if isinstance(value, dict):
                if any(key in value and not value[key].startswith("#") for key in ("$ref", "$dynamicRef")):
                    raise PluginError("Plugin schemas must use local references.")
                for child in value.values():
                    reject_refs(child)
            elif isinstance(value, list):
                for child in value:
                    reject_refs(child)
        reject_refs(schema)
        Draft202012Validator(schema).validate(configuration)
        if len(json.dumps(configuration, allow_nan=False).encode()) > 16384:
            raise PluginError("Plugin configuration exceeds 16 KiB.")
    except (ValidationError, SchemaError, TypeError, ValueError):
        raise PluginError("Configuration does not match the installed plugin schema.") from None


def load_callable(path):
    try:
        module, attribute = path.split(":")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module) or not re.fullmatch(r"[A-Za-z_]\w*", attribute):
            raise ValueError
        function = getattr(importlib.import_module(module), attribute)
        if not callable(function):
            raise ValueError
        return function
    except Exception:
        raise PluginError("Installed plugin entrypoint is unavailable.") from None


def compute_provider(plugin_id, tenant_id, expected_digest=None):
    entry, digest = definition(plugin_id, tenant_id, "compute")
    if expected_digest and expected_digest != digest:
        raise PluginError("Plugin configuration changed; restore it to reconcile its allocations.")
    try:
        secret = os.environ[entry["credential_env"]]
        if not secret:
            raise KeyError
        factory = load_callable(entry["factory"])
        provider = factory(secret)
        if not all(callable(getattr(provider, method, None)) for method in ("catalog", "create", "inspect", "find", "release")):
            raise ValueError
        return provider
    except Exception:
        raise PluginError("Compute plugin or its operator-provisioned credential is unavailable.") from None


def task_executor(plugin_id, configuration, *, tenant_id, digest):
    entry, installed_digest = definition(plugin_id, tenant_id, "task")
    if digest != installed_digest:
        raise PluginError("Task plugin revision is not installed.")
    validate_configuration(entry["configuration_schema"], configuration)
    executor = load_callable(entry["executor"])

    def execute(descriptor, context):
        if str(descriptor.get("tenant_id")) != str(tenant_id):
            raise PluginError("Task plugin tenant mismatch.")
        if not context.heartbeat():
            return None
        try:
            return executor(descriptor, context, configuration)
        except Exception:
            raise PluginError("Custom task plugin failed.") from None
    return execute
