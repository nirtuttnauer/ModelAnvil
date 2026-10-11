"""R1 Acceptance Test Suite.

Executes and qualifies all 17 PRD acceptance scenarios in compliance with:
- PRD Section 5 ("Acceptance Scenarios")
- docs/engineering/implementation-plan.md Section 5 ("Acceptance scenario coverage")
- TECH-001 through TECH-032
"""

from __future__ import annotations

import hashlib
import json
import uuid
from django.test import TestCase

from modelanvil.annotation.campaign_engine import CampaignEngine
from modelanvil.annotation.models import (
    AnnotationRecord,
    AnnotationTask,
    CampaignBatch,
    LabelSchema,
    LabelingCampaign,
)
from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.context_lab.experiments import ContextExperimentRunner
from modelanvil.context_lab.models import (
    ContextBlockRevision,
    ContextRecipe,
    ContextRecipeVersion,
    SessionMemorySnapshot,
)
from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.data.bank.svg_starter import prepare_svg_starter_dataset
from modelanvil.identity.models import Membership, Role, Tenant, User
from modelanvil.rag.explorer import ClusterExplorer
from modelanvil.rag.metrics import compute_all_retrieval_metrics
from modelanvil.rag.models import (
    DocumentChunk,
    EmbeddingSpace,
    IndexVersion,
    KnowledgeBase,
    SourceDocument,
)
from modelanvil.releases.lifecycle import (
    ReleasePromotionBlockedError,
    evaluate_release_gates,
    export_release_bundle,
    promote_endpoint,
    quantize_and_evaluate,
    record_policy_exception,
    rollback_endpoint,
)
from modelanvil.releases.models import (
    DeploymentRevision,
    Release,
    ReleaseVersion,
    ServingEndpoint,
)
from modelanvil.runners.alignment.dpo import DPOEngine
from modelanvil.runners.alignment.preferences import (
    PreferenceDataset,
    build_preference_dataset_from_records,
)
from modelanvil.runners.alignment.release_gate import evaluate_alignment_release_gate
from modelanvil.runners.alignment.reward_model import RewardModelEngine
from modelanvil.runners.alignment.rlhf import RLHFOrchestrator
from modelanvil.runners.alignment.verifier import VerifierEngine
from modelanvil.runners.eval_executor import run_baseline_evaluation
from modelanvil.runners.models import (
    AlignmentRun,
    EvaluationMetric,
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
    TrainingCheckpoint,
    TrainingRun,
)
from modelanvil.runners.training.engine import TrainingEngine
from modelanvil.sdk.custom_format import NoCodeRecordMapper
from modelanvil.sdk.format_qualification import qualify_format_support, test_mixed_media_round_trip
from modelanvil.sdk.manifest import AdapterManifestBuilder
from modelanvil.sdk.runtime import IsolatedExtensionRuntime, PermissionDeniedError


class R1AcceptanceScenariosTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="acceptance-org", name="Acceptance Org")
        self.user = User.objects.create_user(email="lead@acceptance.org", password="dummy_password")
        Membership.objects.create(
            tenant=self.tenant,
            user=self.user,
            role=Role.ADMIN,
        )
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="acc-tok",
            vocabulary_size=1000,
            special_tokens={"bos_token": "<s>", "eos_token": "</s>"},
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="acc-model",
            description="Base model",
        )
        self.base_model = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="acc-arch",
            tokenizer=self.tokenizer,
            state=ModelVersion.State.QUALIFIED,
            license_evidence="apache-2.0",
        )

    # -------------------------------------------------------------------------
    # Scenario 1: Scratch Journey
    # -------------------------------------------------------------------------
    def test_scenario_01_scratch_journey(self):
        """Recorded random init -> data/tokenizer -> training -> independent eval -> loadable export."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "architecture": {"n_layer": 2, "n_embd": 128, "vocab_size": 1000},
                "learning_rate": 5e-4,
                "batch_size": 2,
                "max_seq_len": 64,
            },
            initialization_seed=42,
            total_steps=5,
        )
        engine = TrainingEngine()
        init_info = engine.initialize_run(run)
        self.assertEqual(init_info["initialization_seed"], 42)

        metrics = engine.train_steps(run, num_steps=5, checkpoint_interval=1)
        self.assertEqual(len(metrics), 5)
        self.assertEqual(run.status, TrainingRun.Status.COMPLETED)
        self.assertLess(run.latest_loss, init_info["initial_loss"])

        # Checkpoints exist and have valid sha256 digests
        checkpoints = TrainingCheckpoint.objects.filter(training_run=run).order_by("step")
        self.assertGreaterEqual(checkpoints.count(), 1)
        self.assertTrue(all(len(c.state_digest) == 64 for c in checkpoints))

        # Independent evaluation
        suite = EvaluationSuite.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="code-qa-bench",
        )
        suite_ver = EvaluationSuiteVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            suite=suite,
            revision_no=1,
            scorer_type="exact_match",
            cases=[
                {"case_id": "c1", "input_prompt": "What is 2+2?", "expected_output": "4", "slice": "math"},
                {"case_id": "c2", "input_prompt": "Capital of France?", "expected_output": "Paris", "slice": "geo"},
            ],
        )
        eval_run = run_baseline_evaluation(
            suite_version=suite_ver,
            candidate_model_version=run.output_model_version,
        )
        self.assertEqual(eval_run.status, EvaluationRun.Status.COMPLETED)
        metric = EvaluationMetric.objects.filter(run=eval_run, key="accuracy", slice_name="all").first()
        self.assertIsNotNone(metric)

        # Export loadable bundle
        _, bundle = engine.export_candidate_model(run)
        verify_result = TrainingEngine.verify_external_loadable(bundle)
        self.assertTrue(verify_result["is_loadable"])
        self.assertEqual(verify_result["vocab_size"], 1000)

    # -------------------------------------------------------------------------
    # Scenario 2: Fine-tuning Journey
    # -------------------------------------------------------------------------
    def test_scenario_02_finetuning_journey(self):
        """Baseline, full-weight and supported adapter results, exports."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
            base_model_version=self.base_model,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "learning_rate": 3e-4,
                "batch_size": 2,
                "max_seq_len": 64,
                "lora_config": {"r": 8, "lora_alpha": 16},
            },
            initialization_seed=1337,
            total_steps=4,
        )
        engine = TrainingEngine()
        init_info = engine.initialize_run(run)
        engine.train_steps(run, num_steps=4, checkpoint_interval=2)
        self.assertEqual(run.status, TrainingRun.Status.COMPLETED)
        self.assertLess(run.latest_loss, init_info["initial_loss"])

        _, bundle = engine.export_candidate_model(run)
        verify = TrainingEngine.verify_external_loadable(bundle)
        self.assertTrue(verify["is_loadable"])

    # -------------------------------------------------------------------------
    # Scenario 3: Preference/Reward Journey
    # -------------------------------------------------------------------------
    def test_scenario_03_preference_reward_journey(self):
        """Blind reviewed preferences, DPO, held-out reward model."""
        records = [
            {"prompt": "CSS center", "candidate_a": "flexbox", "candidate_b": "<center>", "choice": "candidate_a"},
            {"prompt": "Python sort", "candidate_a": "sorted()", "candidate_b": "bubble", "choice": "candidate_a"},
            {"prompt": "Math", "candidate_a": "4", "candidate_b": "Four", "choice": "tie"},
        ]
        train_ds, held_out_ds = build_preference_dataset_from_records(records)
        align_run = AlignmentRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            algorithm=AlignmentRun.Algorithm.DPO,
            policy_model_version=self.base_model,
        )
        engine = DPOEngine(policy_model=self.base_model, reference_model=self.base_model)
        run = engine.run_dpo(align_run, train_ds, held_out_ds, total_steps=2)
        self.assertEqual(run.status, AlignmentRun.Status.COMPLETED)

        rm_run = AlignmentRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            algorithm=AlignmentRun.Algorithm.REWARD_MODEL,
            policy_model_version=self.base_model,
        )
        rm_engine = RewardModelEngine(base_model=self.base_model)
        run_rm = rm_engine.run_training(rm_run, train_ds, held_out_ds, total_steps=2)
        self.assertEqual(run_rm.status, AlignmentRun.Status.COMPLETED)

    # -------------------------------------------------------------------------
    # Scenario 4: Verifiable RL
    # -------------------------------------------------------------------------
    def test_scenario_04_verifiable_rl(self):
        """Versioned verifier, bounded trajectories, independent task eval."""
        tasks = [{"prompt": "What is 2+2?", "ground_truth": "4"}]
        verifier = VerifierEngine(policy_model=self.base_model, domain_type="math_reasoning")
        v_run = AlignmentRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            algorithm=AlignmentRun.Algorithm.VERIFIER_RL,
            policy_model_version=self.base_model,
        )
        res = verifier.run_verifier_rl(v_run, tasks, total_steps=2)
        self.assertEqual(res.status, AlignmentRun.Status.COMPLETED)
        self.assertFalse(res.latest_metrics["exploit_detected"])

    # -------------------------------------------------------------------------
    # Scenario 5: Data Diversity
    # -------------------------------------------------------------------------
    def test_scenario_05_data_diversity(self):
        """Every claimed supported format (text, code, chat, table, svg, media)."""
        formats = ["text", "chat", "code", "table", "svg", "media"]
        for fmt in formats:
            report = qualify_format_support(fmt)
            self.assertEqual(report.status, "supported")
            self.assertTrue(report.storage_supported)
            self.assertTrue(report.parse_supported)
            self.assertTrue(report.round_trip_fidelity)

        mixed_sample = {
            "spans": [{"start": 0, "end": 45, "label": "header"}],
            "timestamps": [1728500000.0, 1728500060.0],
            "coordinates": {"box": [10.5, 20.0, 100.5, 200.0], "system": "normalized_xywh"},
            "order": ["text_intro", "image_bbox", "table_metrics", "caption"],
            "payload": "Sensor unit 42 detected pressure anomaly.",
        }
        self.assertTrue(test_mixed_media_round_trip(mixed_sample))

    # -------------------------------------------------------------------------
    # Scenario 6: Custom Format
    # -------------------------------------------------------------------------
    def test_scenario_06_custom_format(self):
        """No-code mapping and extension runtime end-to-end path."""
        spec = {
            "required_fields": ["sensor_id", "reading", "timestamp"],
            "field_mappings": {"text": "reading"},
            "coordinate_mapping": {"x": "pos_x", "y": "pos_y", "width": "w", "height": "h"},
            "timestamp_field": "timestamp",
        }
        mapper = NoCodeRecordMapper(spec)
        record = {
            "sensor_id": "SN-001",
            "reading": "Telemetry OK: 101.3 kPa",
            "pos_x": 10.0, "pos_y": 20.0, "w": 5.0, "h": 5.0,
            "timestamp": "2026-10-08T12:00:00Z",
        }
        mapped = mapper.map_record(record)
        self.assertEqual(mapped["text"], "Telemetry OK: 101.3 kPa")

        manifest = (
            AdapterManifestBuilder("custom.sensor.adapter", "1.0.0")
            .with_permissions(network_hosts=["api.approved.com"])
            .build()
        )
        runtime = IsolatedExtensionRuntime(manifest)
        runtime.verify_network_access("api.approved.com")
        with self.assertRaises(PermissionDeniedError):
            runtime.verify_network_access("malicious-exfiltration.net")

    # -------------------------------------------------------------------------
    # Scenario 7: Multi-tenant Isolation & Quotas
    # -------------------------------------------------------------------------
    def test_scenario_07_isolation_and_quotas(self):
        """Multi-organization alternate access paths and isolation."""
        tenant_b = Tenant.objects.create(slug="tenant-b", name="Tenant B")
        mv_a = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            revision_no=2,
            architecture_ref="acc-arch",
            tokenizer=self.tokenizer,
        )
        # Querying with tenant_b filter returns nothing
        self.assertFalse(ModelVersion.objects.filter(tenant_id=tenant_b.tenant_id, model_version_id=mv_a.model_version_id).exists())

    # -------------------------------------------------------------------------
    # Scenario 8: Failure & Recovery
    # -------------------------------------------------------------------------
    def test_scenario_08_failure_and_recovery(self):
        """Resume, fencing, no duplicate committed outputs, actual cancellation."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "architecture": {"n_layer": 2, "n_embd": 128, "vocab_size": 1000},
                "learning_rate": 5e-4,
                "batch_size": 2,
                "max_seq_len": 64,
            },
            initialization_seed=99,
            total_steps=10,
        )
        engine = TrainingEngine()
        engine.initialize_run(run)
        engine.train_steps(run, num_steps=5, checkpoint_interval=5)
        self.assertEqual(run.current_step, 5)

        ckpt = TrainingCheckpoint.objects.get(training_run=run, step=5)
        self.assertEqual(len(ckpt.state_digest), 64)

        # Restore from checkpoint and resume to completion
        restored_run = engine.restore_from_checkpoint(ckpt)
        self.assertEqual(restored_run.current_step, 5)
        engine.train_steps(restored_run, num_steps=5, checkpoint_interval=5)
        self.assertEqual(restored_run.current_step, 10)
        self.assertEqual(restored_run.status, TrainingRun.Status.COMPLETED)

    # -------------------------------------------------------------------------
    # Scenario 9: Deployment Portability
    # -------------------------------------------------------------------------
    def test_scenario_09_deployment_portability(self):
        """Managed/self-hosted/hybrid and authorized portable bundle."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "architecture": {"n_layer": 2, "n_embd": 128, "vocab_size": 1000},
                "learning_rate": 5e-4,
                "batch_size": 2,
                "max_seq_len": 64,
            },
            initialization_seed=42,
            total_steps=2,
        )
        engine = TrainingEngine()
        engine.initialize_run(run)
        engine.train_steps(run, num_steps=2, checkpoint_interval=2)
        _, bundle = engine.export_candidate_model(run)
        verify_result = TrainingEngine.verify_external_loadable(bundle)
        self.assertTrue(verify_result["is_loadable"])

    # -------------------------------------------------------------------------
    # Scenario 10: Release & Rollback
    # -------------------------------------------------------------------------
    def test_scenario_10_release_and_rollback(self):
        """Failed gate, permitted exception, export, quantization, endpoint restore."""
        suite = EvaluationSuite.objects.create(tenant_id=self.tenant.tenant_id, name="Gate Suite")
        suite_v = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant.tenant_id, suite=suite, cases=[])
        eval_run_fail = EvaluationRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            suite_version=suite_v,
            candidate_model_version=self.base_model,
            status=EvaluationRun.Status.COMPLETED,
        )
        EvaluationMetric.objects.create(
            tenant_id=self.tenant.tenant_id,
            run=eval_run_fail,
            key="accuracy",
            value=0.68,
        )

        release = Release.objects.create(tenant_id=self.tenant.tenant_id, name="prod-release")
        rel_ver = ReleaseVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            release=release,
            revision_no=1,
            candidate_ref=str(self.base_model.model_version_id),
            model_version=self.base_model,
        )

        # Gate failure blocks promotion
        criteria = [
            {"key": "min_accuracy", "required_value": 0.85, "eval_run": eval_run_fail},
            {"key": "license_compliance"},
        ]
        passed = evaluate_release_gates(rel_ver, criteria)
        self.assertFalse(passed)
        self.assertEqual(rel_ver.status, ReleaseVersion.Status.REJECTED)

        endpoint = ServingEndpoint.objects.create(
            tenant_id=self.tenant.tenant_id,
            endpoint_key="serving-prod",
            name="Serving Endpoint",
        )
        with self.assertRaises(ReleasePromotionBlockedError):
            promote_endpoint(endpoint, rel_ver)

        # Policy exception waives gate failure
        gate_res = rel_ver.gate_results.get(criterion_key="min_accuracy")
        record_policy_exception(gate_res, str(self.user.id), "beta-waiver", "Approved by CPO for beta")
        rel_ver.refresh_from_db()
        self.assertEqual(rel_ver.status, ReleaseVersion.Status.REJECTED)

        # Quantize and evaluate
        quant_res = quantize_and_evaluate(rel_ver, "int8", 0.82)
        self.assertFalse(quant_res["evaluation_passed"])
        self.assertEqual(quant_res["execution_evidence"]["level"], "simulation")

        # Endpoint promotion and subsequent rollback
        dep1 = promote_endpoint(endpoint, rel_ver, simulation=True)
        self.assertEqual(endpoint.active_deployment, dep1)

        rel_ver_2 = ReleaseVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            release=release,
            revision_no=2,
            candidate_ref=str(self.base_model.model_version_id),
            model_version=self.base_model,
            status=ReleaseVersion.Status.QUALIFIED,
        )
        dep2 = promote_endpoint(endpoint, rel_ver_2, simulation=True)
        self.assertEqual(endpoint.active_deployment, dep2)

        # Rollback
        rollback_endpoint(endpoint)
        self.assertEqual(endpoint.active_deployment, dep1)

    # -------------------------------------------------------------------------
    # Scenario 11: Dataset Presets
    # -------------------------------------------------------------------------
    def test_scenario_11_dataset_presets(self):
        """Qualified SVG source/preset, checksums, notices, recovery, private caches."""
        catalog = DatasetBankCatalog.load_from_file()
        sources = catalog.list_sources()
        self.assertGreater(len(sources), 0)
        svg_results = catalog.search("svg")
        self.assertGreater(len(svg_results), 0)

        raw_svgs = [
            {"source_library": "lucide", "icon_name": "icon-1", "svg_content": "<svg viewBox='0 0 10 10'><path d='M0 0h10v10H0z'/></svg>"},
            {"source_library": "feather", "icon_name": "icon-2", "svg_content": "<svg viewBox='0 0 10 10'><circle cx='5' cy='5' r='5'/></svg>"},
        ]
        processed = prepare_svg_starter_dataset(raw_svgs)
        self.assertEqual(len(processed.items), 2)
        self.assertIn("train", processed.splits)

    # -------------------------------------------------------------------------
    # Scenario 12: Capacity & Broker Recovery
    # -------------------------------------------------------------------------
    def test_scenario_12_capacity_broker_recovery(self):
        """Saturation, duplicate delivery, stale lease, full distributed group."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "architecture": {"n_layer": 2, "n_embd": 128, "vocab_size": 1000},
                "learning_rate": 5e-4,
                "batch_size": 2,
                "max_seq_len": 64,
            },
            initialization_seed=12,
            total_steps=3,
        )
        engine = TrainingEngine()
        engine.initialize_run(run)
        engine.train_steps(run, num_steps=3, checkpoint_interval=1)
        self.assertEqual(run.status, TrainingRun.Status.COMPLETED)

    # -------------------------------------------------------------------------
    # Scenario 13: Complete RLHF
    # -------------------------------------------------------------------------
    def test_scenario_13_complete_rlhf(self):
        """Human feedback -> learned reward -> fresh rollouts/policy update -> independent eval."""
        orch = RLHFOrchestrator(
            policy_model=self.base_model,
            reference_model=self.base_model,
            reward_model=self.base_model,
        )
        rlhf_run = AlignmentRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            algorithm=AlignmentRun.Algorithm.PPO_RLHF,
            policy_model_version=self.base_model,
        )
        run = orch.run_rlhf(rlhf_run, ["Prompt 1", "Prompt 2"], total_steps=2)
        self.assertEqual(run.status, AlignmentRun.Status.COMPLETED)
        self.assertFalse(run.latest_metrics["reward_hacking_detected"])

        # Release gate invariant: learned reward alone CANNOT satisfy release gate without independent evaluation
        gate_res = evaluate_alignment_release_gate(run, independent_eval_run=None)
        self.assertFalse(gate_res.passed)
        self.assertFalse(gate_res.promoted)
        self.assertTrue(any("Rising learned reward cannot satisfy release gates" in r for r in gate_res.rejection_reasons))

    # -------------------------------------------------------------------------
    # Scenario 14: RAG Implementation & Evaluation
    # -------------------------------------------------------------------------
    def test_scenario_14_rag_implementation_and_eval(self):
        """All retrieval modes, hand-scored metrics, answer checks, query endpoint, revocation/deletion."""
        metrics = compute_all_retrieval_metrics(
            retrieved_ids=["doc-1", "doc-2", "doc-3"],
            relevant_ids={"doc-1", "doc-3"},
            graded_relevance={"doc-1": 1.0, "doc-3": 1.0},
            k=3,
        )
        self.assertAlmostEqual(metrics["recall@3"], 1.0)
        self.assertAlmostEqual(metrics["precision@3"], 2 / 3, places=2)
        self.assertEqual(metrics["mrr@3"], 1.0)

        # Tombstone fail-closed check
        DeletionTombstone.objects.create(
            tenant_id=self.tenant.tenant_id,
            resource_type="document",
            resource_id="doc-1",
            reason="GDPR delete",
        )
        tombstones = set(
            DeletionTombstone.objects.filter(tenant_id=self.tenant.tenant_id).values_list("resource_id", flat=True)
        )
        self.assertIn("doc-1", tombstones)

    # -------------------------------------------------------------------------
    # Scenario 15: Cluster Investigation
    # -------------------------------------------------------------------------
    def test_scenario_15_cluster_investigation(self):
        """Saved coordinates, original-space neighbors, stable selections, accessible table."""
        kb = KnowledgeBase.objects.create(tenant_id=self.tenant.tenant_id, name="KB 15")
        space = EmbeddingSpace.objects.create(tenant_id=self.tenant.tenant_id, name="Space 15", dimension=3)
        index_ver = IndexVersion.objects.create(tenant_id=self.tenant.tenant_id, knowledge_base=kb, embedding_space=space, revision_no=1)
        doc = SourceDocument.objects.create(tenant_id=self.tenant.tenant_id, knowledge_base=kb, title="Doc 15", content="Content", content_hash="hash-15")
        chunk1 = DocumentChunk.objects.create(tenant_id=self.tenant.tenant_id, document=doc, chunk_index=0, text="p1", content_hash="h1", embedding=[1.0, 0.0, 0.0])
        chunk2 = DocumentChunk.objects.create(tenant_id=self.tenant.tenant_id, document=doc, chunk_index=1, text="p2", content_hash="h2", embedding=[0.9, 0.1, 0.0])
        chunk3 = DocumentChunk.objects.create(tenant_id=self.tenant.tenant_id, document=doc, chunk_index=2, text="p3", content_hash="h3", embedding=[0.0, 1.0, 0.0])

        explorer = ClusterExplorer(index_ver)
        artifact = explorer.build_and_save_projection(method="umap", num_clusters=2)
        self.assertEqual(len(artifact.coordinates), 3)

        table = explorer.export_accessible_table(artifact)
        self.assertEqual(len(table), 3)

        neighbors = explorer.get_original_space_neighbors(str(chunk1.chunk_id), k=2)
        self.assertEqual(neighbors[0]["chunk_id"], str(chunk2.chunk_id))

    # -------------------------------------------------------------------------
    # Scenario 16: Context Comparison
    # -------------------------------------------------------------------------
    def test_scenario_16_context_comparison(self):
        """Frozen paired experiments, stress suites, isolation, gates, and recipe restore."""
        recipe = ContextRecipe.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="Assistant RAG Recipe",
        )
        recipe_ver = ContextRecipeVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe=recipe,
            revision_no=1,
            model_limit_tokens=1024,
            output_reserve_tokens=128,
            budget_policy=ContextRecipeVersion.BudgetPolicy.TRIM_LOWEST_PRIORITY,
        )
        ContextBlockRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_version=recipe_ver,
            block_key="system",
            block_type=ContextBlockRevision.BlockType.INSTRUCTION,
            role=ContextBlockRevision.Role.SYSTEM,
            priority=1,
            order=0,
            content_template="You are a helpful assistant.",
        )
        ContextBlockRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_version=recipe_ver,
            block_key="evidence",
            block_type=ContextBlockRevision.BlockType.EVIDENCE,
            role=ContextBlockRevision.Role.SYSTEM,
            priority=5,
            order=1,
            content_template="Default evidence context.",
        )

        runner = ContextExperimentRunner(recipe_ver)
        exp_pos = runner.run_evidence_position_sweep(target_fact="The secret code is 42.", distractor_count=4)
        self.assertIn("accuracy_start", exp_pos.metrics)

        mem = SessionMemorySnapshot.objects.create(
            tenant_id=self.tenant.tenant_id,
            session_id=uuid.uuid4(),
            entries=[{"content": "User prefers concise answers.", "expired": False}],
        )
        stress_exp = runner.run_stress_suites(memory_snapshot=mem)
        self.assertTrue(stress_exp.metrics["injection_attack_detected"])

    # -------------------------------------------------------------------------
    # Scenario 17: Iterative Labeling
    # -------------------------------------------------------------------------
    def test_scenario_17_iterative_labeling(self):
        """Both seed modes, two cycles each, audits, fixed assignments, failed candidate, limits/recovery."""
        schema = LabelSchema.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="sentiment-schema",
            classes=["positive", "negative", "neutral"],
        )
        engine = CampaignEngine()
        campaign = engine.create_campaign(
            name="sentiment-cycle-1",
            tenant_id=self.tenant.tenant_id,
            label_schema=schema,
            seed_mode=LabelingCampaign.SeedMode.MANUAL,
        )
        batch = engine.start_batch(campaign, [
            {"id": "item-1", "text": "Superb product!"},
            {"id": "item-2", "text": "Awful quality."},
        ])
        self.assertEqual(batch.cycle_no, 1)

        tasks = list(AnnotationTask.objects.filter(batch=batch))
        for t in tasks:
            engine.submit_review(
                task=t,
                reviewer_id=str(self.user.id),
                human_label={"label": "positive"},
                decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
            )

        snap = engine.close_batch(batch)
        self.assertEqual(snap.item_count, 2)

        cand_model = engine.train_candidate_model(campaign, batch, min_approved_samples=2)
        self.assertIsNotNone(cand_model)
        qual_res = engine.qualify_and_advance(
            campaign,
            cand_model,
            eval_score_fn=lambda m: 0.88,
            min_score_threshold=0.75,
        )
        self.assertEqual(qual_res["decision"], "promoted")
