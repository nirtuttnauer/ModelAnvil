"""Acceptance and unit tests for WP-13 Context Lab: Compiler, token budgets, multi-turn stress suites, and rollbacks."""
import uuid
from django.test import TestCase

from modelanvil.context_lab.compiler import (
    ContextCompiler,
    ContextOverflowError,
    estimate_tokens,
)
from modelanvil.context_lab.experiments import ContextExperimentRunner
from modelanvil.context_lab.models import (
    ContextBlockRevision,
    ContextExperiment,
    ContextRecipe,
    ContextRecipeVersion,
    SessionMemorySnapshot,
)
from modelanvil.identity.models import Tenant


class ContextLabTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="context-test-tenant", name="Context Test Tenant")
        self.tenant_id = self.tenant.tenant_id

        self.recipe = ContextRecipe.objects.create(
            tenant_id=self.tenant_id,
            name="Assistant RAG Recipe",
            description="Production assistant recipe with system instructions, evidence, and history",
        )

        self.v1 = ContextRecipeVersion.objects.create(
            tenant_id=self.tenant_id,
            recipe=self.recipe,
            revision_no=1,
            model_limit_tokens=2048,
            output_reserve_tokens=256,
            budget_policy=ContextRecipeVersion.BudgetPolicy.TRIM_LOWEST_PRIORITY,
            status=ContextRecipeVersion.Status.PROMOTED,
        )

        # Blocks for v1
        self.b_sys = ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=self.v1,
            block_key="system_instruction",
            block_type=ContextBlockRevision.BlockType.INSTRUCTION,
            role=ContextBlockRevision.Role.SYSTEM,
            priority=1,  # Critical, never trimmed
            order=0,
            content_template="You are a helpful, harmless, and honest assistant.",
        )
        self.b_ev = ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=self.v1,
            block_key="evidence",
            block_type=ContextBlockRevision.BlockType.EVIDENCE,
            role=ContextBlockRevision.Role.SYSTEM,
            priority=2,
            order=1,
            content_template="",
        )
        self.b_hist = ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=self.v1,
            block_key="history",
            block_type=ContextBlockRevision.BlockType.HISTORY,
            role=ContextBlockRevision.Role.USER,
            priority=3,
            order=2,
            content_template="",
        )
        self.b_mem = ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=self.v1,
            block_key="memory",
            block_type=ContextBlockRevision.BlockType.MEMORY,
            role=ContextBlockRevision.Role.SYSTEM,
            priority=4,
            order=3,
            content_template="",
        )
        self.b_tool = ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=self.v1,
            block_key="tool_results",
            block_type=ContextBlockRevision.BlockType.TOOL_RESULT,
            role=ContextBlockRevision.Role.TOOL,
            priority=5,
            order=4,
            content_template="",
        )

    def test_compiler_ordering_and_output_reserve_budgeting(self):
        """TECH-026: Typed blocks compile in order, enforce output reserve, and track token counts."""
        compiler = ContextCompiler(self.v1)
        res = compiler.compile({
            "evidence": "Quantum computers use qubits with complex state spaces.",
            "history": "User: What is superposition?\nAssistant: Superposition allows states 0 and 1 together.",
        })

        self.assertGreater(res.total_input_tokens, 0)
        self.assertEqual(res.output_reserve_tokens, 256)
        self.assertEqual(res.model_limit_tokens, 2048)
        self.assertLessEqual(res.total_input_tokens + res.output_reserve_tokens, res.model_limit_tokens)

        # Verify block serialization order: system_instruction -> evidence -> history
        self.assertIn("You are a helpful, harmless, and honest assistant", res.serialized_prompt)
        self.assertIn("Quantum computers use qubits", res.serialized_prompt)
        self.assertIn("What is superposition", res.serialized_prompt)

    def test_compiler_preserves_saved_and_overridden_whitespace(self):
        template = "  Saved instruction\n"
        self.b_sys.content_template = template
        self.b_sys.save(update_fields=['content_template'])
        override = "    print('exact source')\n\n"
        result = ContextCompiler(self.v1).compile({'evidence': override})
        self.assertEqual(result.included_blocks[0].rendered_content, template)
        self.assertEqual(result.included_blocks[1].rendered_content, override)
        self.assertIn(f'<|im_start|>system\n{template}<|im_end|>', result.serialized_prompt)
        self.assertIn(f'<|im_start|>system\n{override}<|im_end|>', result.serialized_prompt)

    def test_context_overflow_policies(self):
        """TECH-026: Strict overflow raises ContextOverflowError, trim policy drops lowest priority blocks."""
        # 1. Test fail-on-overflow
        v_strict = ContextRecipeVersion.objects.create(
            tenant_id=self.tenant_id,
            recipe=self.recipe,
            revision_no=2,
            model_limit_tokens=200,  # small budget
            output_reserve_tokens=50,
            budget_policy=ContextRecipeVersion.BudgetPolicy.FAIL_ON_OVERFLOW,
        )
        ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=v_strict,
            block_key="huge_evidence",
            block_type=ContextBlockRevision.BlockType.EVIDENCE,
            priority=2,
            order=0,
            content_template="word " * 500,  # exceeds 150 token budget
        )

        compiler_strict = ContextCompiler(v_strict)
        with self.assertRaises(ContextOverflowError):
            compiler_strict.compile({})

        # 2. Test trim-lowest-priority policy
        v_trim = ContextRecipeVersion.objects.create(
            tenant_id=self.tenant_id,
            recipe=self.recipe,
            revision_no=3,
            model_limit_tokens=300,
            output_reserve_tokens=50,
            budget_policy=ContextRecipeVersion.BudgetPolicy.TRIM_LOWEST_PRIORITY,
        )
        ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=v_trim,
            block_key="system_prompt",
            block_type=ContextBlockRevision.BlockType.INSTRUCTION,
            priority=1,
            order=0,
            content_template="Crucial system instruction.",
        )
        ContextBlockRevision.objects.create(
            tenant_id=self.tenant_id,
            recipe_version=v_trim,
            block_key="low_prio_evidence",
            block_type=ContextBlockRevision.BlockType.EVIDENCE,
            priority=8,
            order=1,
            content_template="extra word " * 400,
        )

        compiler_trim = ContextCompiler(v_trim)
        res_trim = compiler_trim.compile({})
        self.assertEqual(len(res_trim.included_blocks), 1)
        self.assertEqual(res_trim.included_blocks[0].block_key, "system_prompt")
        self.assertEqual(len(res_trim.omitted_blocks), 1)
        self.assertEqual(res_trim.omitted_blocks[0]["block_key"], "low_prio_evidence")

    def test_history_strategy_comparison(self):
        """PRD Scenario 16: Paired comparison of full, windowed, and summarized history."""
        turns = [
            {"role": "User", "content": "Turn 1: My name is Alice."},
            {"role": "Assistant", "content": "Turn 2: Hello Alice!"},
            {"role": "User", "content": "Turn 3: I live in Seattle."},
            {"role": "Assistant", "content": "Turn 4: Seattle is known for rain and tech."},
            {"role": "User", "content": "Turn 5: What is my name and location?"},
        ]

        runner = ContextExperimentRunner(self.v1)
        exp = runner.run_history_strategy_comparison(turns)

        self.assertEqual(exp.stress_type, "history_strategy_comparison")
        self.assertGreater(exp.metrics["full_history_tokens"], exp.metrics["windowed_history_tokens"])
        self.assertGreater(exp.metrics["token_reduction_pct"], 0)

    def test_evidence_position_sweep_reports_recall_not_run(self):
        """Prompt inspection must not manufacture model recall or a middle dip."""
        runner = ContextExperimentRunner(self.v1)
        exp = runner.run_evidence_position_sweep(
            target_fact="The secret code is OMEGA-42.", distractor_count=6
        )

        self.assertEqual(exp.stress_type, "position_sweep")
        exp.refresh_from_db()
        self.assertEqual(exp.metrics, {
            "status": "not_run",
            "reason": "Recall evaluation requires model execution; only prompt compilation was performed.",
        })
        self.assertEqual(set(exp.details), {"start", "middle", "end"})
        for details in exp.details.values():
            self.assertEqual(set(details), {"tokens", "fact_retained"})
            self.assertGreater(details["tokens"], 0)
            self.assertTrue(details["fact_retained"])

    def test_multi_turn_stress_safety_suites(self):
        """PRD Scenario 16 & TECH-027: Injection attack, stale memory isolation, and tool error handling."""
        snapshot = SessionMemorySnapshot.objects.create(
            tenant_id=self.tenant_id,
            session_key="session-user-123",
            revision_no=1,
            entries=[
                {"content": "Alice's current city is Seattle.", "expired": False},
                {"content": "Alice's old temporary hotel was Room 404.", "expired": True},  # Expired!
            ],
        )

        runner = ContextExperimentRunner(self.v1)
        exp = runner.run_stress_suites(memory_snapshot=snapshot)

        self.assertTrue(exp.metrics["injection_attack_detected"])
        self.assertTrue(exp.metrics["stale_memory_isolated"])
        self.assertTrue(exp.metrics["tool_error_handled"])
        self.assertTrue(exp.metrics["stress_suite_passed"])

    def test_session_isolation(self):
        """PRD Scenario 16: Memory snapshots belonging to Session A cannot be observed by Session B."""
        snap_a = SessionMemorySnapshot.objects.create(
            tenant_id=self.tenant_id,
            session_key="session-a",
            entries=[{"content": "Confidential Project Titan data for Alice.", "expired": False}],
        )
        snap_b = SessionMemorySnapshot.objects.create(
            tenant_id=self.tenant_id,
            session_key="session-b",
            entries=[{"content": "Bob general preferences.", "expired": False}],
        )

        compiler = ContextCompiler(self.v1)
        res_b = compiler.compile({}, memory_snapshot=snap_b)

        # Ensure Bob's compiled prompt contains Bob's memory and none of Alice's
        self.assertIn("Bob general preferences", res_b.serialized_prompt)
        self.assertNotIn("Project Titan", res_b.serialized_prompt)

    def test_recipe_rollback_on_failed_gate(self):
        """PRD Scenario 16: Failing promotion gate restores previous promoted recipe."""
        # Create a v2 in draft
        v2 = ContextRecipeVersion.objects.create(
            tenant_id=self.tenant_id,
            recipe=self.recipe,
            revision_no=2,
            model_limit_tokens=1024,
            output_reserve_tokens=128,
            status=ContextRecipeVersion.Status.DRAFT,
        )

        runner_v2 = ContextExperimentRunner(v2)
        restored = runner_v2.restore_previous_recipe()

        self.assertEqual(restored.revision_no, 1)
        self.assertEqual(restored.status, ContextRecipeVersion.Status.PROMOTED)
        v2.refresh_from_db()
        self.assertEqual(v2.status, ContextRecipeVersion.Status.ARCHIVED)
