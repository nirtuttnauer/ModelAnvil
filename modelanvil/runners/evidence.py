"""Server-owned descriptions of current execution paths; metadata is not qualification."""
from __future__ import annotations

EVIDENCE_DOC = "/docs/engineering/capability-evidence.md"


def evidence(level="unknown", source="No verified execution evidence recorded"):
    return {
        "level": level,
        "source": source,
        "production_qualified": False,
        "hardware_qualified": False,
        "documentation": EVIDENCE_DOC,
    }


def training_evidence(run):
    from modelanvil.runners.training import registry
    if registry.is_worker_run(run):
        pins = (run.hardware_config or {}).get('pins', {})
        module = registry.runtime_for_run(run)
        if pins.get('contract_digest') == module.CONTRACT_DIGEST and run.job_id:
            if module.RUNTIME_ID == registry.CHARACTER_RUNTIME_ID:
                source = ('Pinned CPU character SFT; measured metrics and fenced checkpoints' if run.current_step
                          else 'Budgeted CPU worker job awaiting checkpoint evidence')
            else:
                source = ('Pinned general transformer SFT; measured metrics and fenced checkpoints' if run.current_step
                          else 'Budgeted CPU worker job awaiting checkpoint evidence')
            if pins.get('accelerator'):
                backend = pins['accelerator']['device']['backend']
                recipe = 'LoRA' if pins.get('recipe') == 'lora_adapter' else 'full SFT'
                source = (f'Pinned SmolLM2 {backend} {recipe}; measured GPU metrics and fenced checkpoints'
                          if run.current_step else f'Budgeted {backend} GPU worker job awaiting checkpoint evidence')
            result = evidence('integrated_execution' if run.current_step else 'configuration_only', source)
            result['runtime_scope'] = module.RUNTIME_ID
            return result
        return evidence('unknown', 'Recorded worker run uses an earlier or unrecognized runtime contract; current verification unavailable')
    return evidence("simulation", "CPU numerical fixture: synthetic token sequences; no pinned dataset/base-weight execution")


def model_evidence(model):
    from modelanvil.runners.models import AlignmentRun, TrainingRun
    run = TrainingRun.all_objects.filter(tenant_id=model.tenant_id, output_model_version=model,
                                        status=TrainingRun.Status.COMPLETED).first()
    if run:
        result = training_evidence(run)
        return result
    alignment = AlignmentRun.all_objects.filter(tenant_id=model.tenant_id,
        output_model_version=model, status=AlignmentRun.Status.COMPLETED).exclude(execution_pins={}).first()
    if alignment:
        result = evidence('integrated_execution',
            f'Candidate produced by pinned CPU character {alignment.algorithm} alignment; measured checkpoints and held-out scores')
        result['runtime_scope'] = 'modelanvil.cpu-character-alignment.v1'
        return result
    if model.metadata.get("source_run_id"):
        return evidence("simulation", "Candidate from CPU training/alignment fixture")
    return evidence("configuration_only", "Registry metadata; weights and hardware qualification not verified")


def evaluation_evidence(run):
    origin = (run.protocol_ref or {}).get("execution_evidence", {})
    if origin.get("level") in ("simulation", "integrated_execution"):
        return evidence(origin["level"], origin.get("source", "Evaluation callback"))
    if run.status == 'pending':
        return evidence('configuration_only', 'Saved evaluation configuration; no inference has executed.')
    return evidence()


def release_evidence(version):
    return evidence("configuration_only", "Release gates and endpoint pointers; production serving qualification unavailable")
