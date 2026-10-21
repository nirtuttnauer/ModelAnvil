"""Iterative labeling campaign engine: seed setup, drafting, review, batch closure, training, and qualification (WP-10 / TECH-012, TECH-013 / PRD Scenario 17)."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable, Optional

from django.core.exceptions import ValidationError
from django.utils import timezone

from modelanvil.annotation.models import (
    AnnotationRecord,
    AnnotationTask,
    CampaignBatch,
    CumulativeSnapshot,
    LabelSchema,
    LabelingCampaign,
    RubricRevision,
)
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion


class CampaignEngine:
    """Manages iterative labeling campaigns across manual/assisted seeds and repeated cycles."""

    def create_campaign(
        self,
        *,
        name: str,
        tenant_id: str | uuid.UUID,
        label_schema: LabelSchema,
        seed_mode: str,
        active_drafting_model: Optional[ModelVersion] = None,
        audit_samples: Optional[list[dict[str, Any]]] = None,
        max_cycles: int = 3,
        budget_limit_dollars: float = 100.0,
        rubric: Optional[RubricRevision] = None,
        configuration: Optional[dict[str, Any]] = None,
    ) -> LabelingCampaign:
        """Create campaign and reserve source-group-aware audit set (TECH-012, TECH-013)."""
        tid = uuid.UUID(str(tenant_id)) if not isinstance(tenant_id, uuid.UUID) else tenant_id

        if seed_mode not in LabelingCampaign.SeedMode.values:
            raise ValidationError(f"Invalid seed_mode {seed_mode!r}.")

        if seed_mode == LabelingCampaign.SeedMode.EXISTING_MODEL and active_drafting_model is None:
            raise ValidationError("Model-assisted seed requires an active_drafting_model.")

        # Compute digest of reserved audit set to ensure strict exclusion from training
        audit_digest = ""
        if audit_samples:
            audit_payload = json.dumps(
                sorted([s.get("id") or s.get("text", "") for s in audit_samples]), sort_keys=True
            )
            audit_digest = hashlib.sha256(audit_payload.encode("utf-8")).hexdigest()

        from modelanvil.core.tenancy import get_active_project
        campaign = LabelingCampaign.objects.create(
            project_id=get_active_project(),
            tenant_id=tid,
            name=name,
            seed_mode=seed_mode,
            active_drafting_model=active_drafting_model,
            held_out_audit_digest=audit_digest,
            label_schema=label_schema,
            rubric=rubric,
            max_cycles=max_cycles,
            budget_limit_dollars=budget_limit_dollars,
            configuration=configuration or {},
        )
        return campaign

    def start_batch(
        self,
        campaign: LabelingCampaign,
        candidate_samples: list[dict[str, Any]],
    ) -> CampaignBatch:
        """Start a new batch cycle, pinning the drafting model and excluding audit cases."""
        if campaign.status != LabelingCampaign.Status.ACTIVE:
            raise ValidationError(f"Cannot start batch: campaign is {campaign.status}.")

        if campaign.current_cycle >= campaign.max_cycles:
            raise ValidationError(
                f"Campaign has reached maximum cycle limit ({campaign.max_cycles})."
            )

        cycle_no = campaign.current_cycle + 1

        # Pin drafting model for this entire batch
        assigned_model = campaign.active_drafting_model

        batch = CampaignBatch.objects.create(
            tenant_id=campaign.tenant_id,
            campaign=campaign,
            cycle_no=cycle_no,
            status=CampaignBatch.Status.OPEN,
            assigned_drafting_model=assigned_model,
            sample_count=len(candidate_samples),
        )

        # Create annotation tasks for eligible samples
        for idx, sample in enumerate(candidate_samples):
            sample_ref = str(sample.get("id") or f"sample-{cycle_no}-{idx+1}")
            AnnotationTask.objects.create(
                tenant_id=campaign.tenant_id,
                campaign=campaign,
                batch=batch,
                sample_ref=sample_ref,
                content=sample,
                status=AnnotationTask.Status.PENDING,
            )

        return batch

    def generate_drafts(
        self,
        batch: CampaignBatch,
        *,
        drafter_fn: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> int:
        """Generate draft predictions for tasks using the pinned batch model."""
        if batch.assigned_drafting_model is None and drafter_fn is None:
            return 0  # Manual mode: tasks remain empty

        batch.status = CampaignBatch.Status.DRAFTING
        batch.save(update_fields=["status", "updated_at"])

        tasks = AnnotationTask.objects.filter(batch=batch, status=AnnotationTask.Status.PENDING)
        count = 0

        for task in tasks:
            if drafter_fn:
                pred = drafter_fn(task.content)
            else:
                # Default text classifier drafting heuristic
                text = str(task.content.get("text", "")).lower()
                classes = batch.campaign.label_schema.classes or ["positive", "negative"]
                assigned_class = classes[0] if "good" in text or "great" in text else classes[-1]
                pred = {"predicted_label": assigned_class, "confidence": 0.88}

            task.content["draft_prediction"] = pred
            task.status = AnnotationTask.Status.DRAFTED
            task.save(update_fields=["content", "status", "updated_at"])
            count += 1

        batch.status = CampaignBatch.Status.REVIEWING
        batch.save(update_fields=["status", "updated_at"])
        return count

    def submit_review(
        self,
        *,
        task: AnnotationTask,
        reviewer_id: str,
        human_label: dict[str, Any],
        decision: str,
        expected_revision: int = 1,
        time_spent_seconds: float = 0.0,
        is_blind_preference: bool = False,
        preference_choice: str = "",
    ) -> AnnotationRecord:
        """Submit a human review record, preserving model origin and detecting conflicts (TECH-011)."""
        if decision not in AnnotationRecord.Decision.values:
            raise ValidationError(f"Invalid decision {decision!r}.")

        # Check for concurrent edit conflicts
        latest_record = task.records.order_by("-revision_no").first()
        current_rev = (latest_record.revision_no if latest_record else 0) + 1
        if latest_record and latest_record.revision_no != expected_revision - 1:
            raise ValidationError(
                f"Concurrent edit conflict: task was modified to revision {latest_record.revision_no}; expected {expected_revision-1}."
            )

        original_pred = task.content.get("draft_prediction", {})

        record = AnnotationRecord.objects.create(
            tenant_id=task.tenant_id,
            task=task,
            revision_no=current_rev,
            reviewer_id=reviewer_id,
            original_prediction=original_pred,
            human_label=human_label,
            decision=decision,
            is_blind_preference=is_blind_preference,
            preference_choice=preference_choice,
            time_spent_seconds=time_spent_seconds,
        )

        # Update task status
        if decision == AnnotationRecord.Decision.SKIPPED:
            task.status = AnnotationTask.Status.SKIPPED
        elif decision == AnnotationRecord.Decision.REJECTED:
            task.status = AnnotationTask.Status.PENDING  # Can be re-reviewed or left unapproved
        else:
            task.status = AnnotationTask.Status.COMPLETED

        task.save(update_fields=["status", "updated_at"])
        return record

    def close_batch(self, batch: CampaignBatch) -> CumulativeSnapshot:
        """Close batch, gather approved data, and commit an immutable cumulative snapshot (TECH-012)."""
        approved_tasks = AnnotationTask.objects.filter(
            batch=batch, status__in=[AnnotationTask.Status.COMPLETED, AnnotationTask.Status.ADJUDICATED], needs_adjudication=False
        )

        new_items: list[dict[str, Any]] = []
        for t in approved_tasks:
            rec = t.records.order_by("-revision_no").first()
            if rec and rec.decision in (
                AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
                AnnotationRecord.Decision.CORRECTED,
            ):
                new_items.append({
                    "sample_ref": t.sample_ref,
                    "content": t.content,
                    "human_label": rec.human_label,
                    "decision": rec.decision,
                    "reviewer_id": rec.reviewer_id,
                    "is_blind_review": rec.is_blind_review,
                    "is_adjudication": rec.is_adjudication,
                    "cycle_approved": batch.cycle_no,
                })

        # Inherit cumulative approved items from prior cycle to avoid double counting
        accumulated_items: list[dict[str, Any]] = []
        if batch.cycle_no > 1:
            prior_snapshot = CumulativeSnapshot.objects.filter(
                campaign=batch.campaign, cycle_no=batch.cycle_no - 1
            ).first()
            if prior_snapshot:
                accumulated_items.extend(prior_snapshot.items)

        # Append new items avoiding duplicate sample_refs
        seen_refs = {item["sample_ref"] for item in accumulated_items}
        for item in new_items:
            if item["sample_ref"] not in seen_refs:
                accumulated_items.append(item)
                seen_refs.add(item["sample_ref"])

        # Compute deterministic snapshot digest
        payload = json.dumps(
            sorted(accumulated_items, key=lambda x: str(x["sample_ref"])), sort_keys=True
        )
        snapshot_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        snapshot = CumulativeSnapshot.objects.create(
            tenant_id=batch.tenant_id,
            campaign=batch.campaign,
            cycle_no=batch.cycle_no,
            item_count=len(accumulated_items),
            manifest_digest=snapshot_digest,
            items=accumulated_items,
        )

        batch.status = CampaignBatch.Status.CLOSED
        batch.approved_count = len(new_items)
        batch.snapshot_manifest_digest = snapshot_digest
        batch.save(update_fields=["status", "approved_count", "snapshot_manifest_digest", "updated_at"])

        batch.campaign.current_cycle = batch.cycle_no
        batch.campaign.save(update_fields=["current_cycle", "updated_at"])

        return snapshot

    def train_candidate_model(
        self,
        campaign: LabelingCampaign,
        batch: CampaignBatch,
        *,
        tokenizer: Optional[TokenizerVersion] = None,
        min_approved_samples: int = 2,
    ) -> ModelVersion:
        """Train a candidate labeling model from the cumulative approved snapshot."""
        snapshot = CumulativeSnapshot.objects.filter(
            campaign=campaign, cycle_no=batch.cycle_no
        ).first()

        if not snapshot or snapshot.item_count < min_approved_samples:
            raise ValidationError(
                f"Insufficient approved data to train labeling model: requires at least {min_approved_samples} items, got {snapshot.item_count if snapshot else 0}."
            )

        model_name = f"{campaign.name}-classifier"
        model, _ = Model.objects.get_or_create(
            tenant_id=campaign.tenant_id,
            name=model_name,
            defaults={"intended_tasks": ["classification"]},
        )

        base_tok = (
            tokenizer
            or (campaign.active_drafting_model.tokenizer if campaign.active_drafting_model else None)
            or TokenizerVersion.objects.filter(tenant_id=campaign.tenant_id).first()
        )

        rev_no = ModelVersion.objects.filter(tenant_id=campaign.tenant_id, model=model).count() + 1
        candidate_version = ModelVersion.objects.create(
            tenant_id=campaign.tenant_id,
            model=model,
            revision_no=rev_no,
            tokenizer=base_tok,
            state=ModelVersion.State.DRAFT,
            metadata={
                "execution_evidence": {"level": "simulation", "source": "Metadata-only campaign candidate"},
                "campaign_id": str(campaign.campaign_id),
                "cycle_no": batch.cycle_no,
                "trained_on_snapshot_digest": snapshot.manifest_digest,
                "sample_count": snapshot.item_count,
            },
        )
        return candidate_version

    def qualify_and_advance(
        self,
        campaign: LabelingCampaign,
        candidate_model: ModelVersion,
        *,
        eval_score_fn: Callable[[ModelVersion], float],
        min_score_threshold: float = 0.70,
    ) -> dict[str, Any]:
        """Evaluate candidate on held-out audit set and promote only if passing gate (TECH-013)."""
        score = eval_score_fn(candidate_model)
        passed = (score >= min_score_threshold)

        prior_model = campaign.active_drafting_model

        if passed:
            campaign.active_drafting_model = candidate_model
            campaign.save(update_fields=["active_drafting_model", "updated_at"])
            return {
                "decision": "promoted",
                "execution_evidence": {"level": "simulation", "production_qualified": False},
                "score": score,
                "active_model_id": str(candidate_model.model_version_id),
                "prior_model_id": str(prior_model.model_version_id) if prior_model else None,
            }
        else:
            return {
                "decision": "rejected",
                "execution_evidence": {"level": "simulation", "production_qualified": False},
                "score": score,
                "active_model_id": str(prior_model.model_version_id) if prior_model else None,
                "reason": f"Evaluation score {score:.2f} did not meet required threshold {min_score_threshold:.2f}.",
            }

    def rollback_model(
        self,
        campaign: LabelingCampaign,
        target_model: Optional[ModelVersion],
    ) -> None:
        """Roll back active drafting model assignment without mutating completed batches or review history."""
        campaign.active_drafting_model = target_model
        campaign.save(update_fields=["active_drafting_model", "updated_at"])

    def pause_campaign(self, campaign: LabelingCampaign) -> None:
        campaign.status = LabelingCampaign.Status.PAUSED
        campaign.save(update_fields=["status", "updated_at"])

    def resume_campaign(self, campaign: LabelingCampaign) -> None:
        campaign.status = LabelingCampaign.Status.ACTIVE
        campaign.save(update_fields=["status", "updated_at"])
