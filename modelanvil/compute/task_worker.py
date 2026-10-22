"""Execute only the task plugin pinned by an operator at process startup."""
import os

from modelanvil.compute.plugins import PluginError, definition, task_executor


def execute_task(plugin_id, tenant_id, descriptor, context):
    entry, digest = definition(plugin_id, tenant_id, "task")
    required = descriptor.get("requirements", {})
    if required.get("task_plugin") != plugin_id or required.get("task_plugin_digest") != digest:
        raise PluginError("Job does not target this installed plugin revision.")
    return task_executor(plugin_id, descriptor.get("payload", {}).get("configuration", {}),
                         tenant_id=tenant_id, digest=digest)(descriptor, context)


def execute(descriptor, context):
    # Environment is provisioned by the operator, not copied from job payloads.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")
    return execute_task(os.environ["MODELANVIL_TASK_PLUGIN"], os.environ["MODELANVIL_TENANT_ID"], descriptor, context)
