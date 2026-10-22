"""Dispatch managed local jobs without letting the browser choose an executor."""


def managed_executor(descriptor, context):
    payload = descriptor.get('payload') or {}
    if payload.get('type') == 'qualified_evaluation':
        from modelanvil.runners.eval_worker import evaluation_worker_executor
        return evaluation_worker_executor(descriptor, context)
    from modelanvil.runners.training.executor import training_worker_executor
    return training_worker_executor(descriptor, context)
