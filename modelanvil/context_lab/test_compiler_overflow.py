"""Overflow, omission, and truncation records from context compilation."""

import json
from dataclasses import asdict

from django.test import TestCase

from modelanvil.context_lab.compiler import ContextCompiler, ContextOverflowError, estimate_tokens
from modelanvil.context_lab.models import ContextBlockRevision, ContextRecipe, ContextRecipeVersion
from modelanvil.core.tenancy import reset_context, set_active_tenant
from modelanvil.identity.models import Tenant


class CompilerOverflowTests(TestCase):
    def setUp(self):
        reset_context()
        self.tenant = Tenant.objects.create(slug="compiler-overflow", name="Compiler overflow")
        set_active_tenant(self.tenant.pk)
        self.addCleanup(reset_context)
        self.recipe = ContextRecipe.all_objects.create(tenant_id=self.tenant.pk, name="Overflow")

    def make_version(self, policy, limit=100000, reserve=1):
        return ContextRecipeVersion.all_objects.create(
            tenant_id=self.tenant.pk,
            recipe=self.recipe,
            revision_no=self.recipe.versions.count() + 1,
            model_limit_tokens=limit,
            output_reserve_tokens=reserve,
            budget_policy=policy,
        )

    def add_block(self, version, key, text, priority=2, kind="evidence", **extra):
        return ContextBlockRevision.all_objects.create(
            tenant_id=self.tenant.pk,
            recipe_version=version,
            block_key=key,
            block_type=kind,
            role="user",
            order=version.blocks.count(),
            priority=priority,
            content_template=text,
            **extra,
        )

    def set_budget(self, version, max_budget, reserve=1):
        version.output_reserve_tokens = reserve
        version.model_limit_tokens = max_budget + reserve
        version.save(update_fields=["output_reserve_tokens", "model_limit_tokens"])

    def assert_no_readiness_claim(self, text):
        lowered = text.lower()
        self.assertNotIn("qualified", lowered)
        self.assertNotIn("production-ready", lowered)

    def test_strict_budget_raises_context_overflow_error(self):
        version = self.make_version(ContextRecipeVersion.BudgetPolicy.FAIL_ON_OVERFLOW)
        self.add_block(version, "instruction", "Keep.", priority=1, kind="instruction")
        self.add_block(version, "evidence", "evidence " * 80, priority=4, kind="evidence")
        compiler = ContextCompiler(version)
        full = compiler.compile({})
        instruction = compiler.compile({"evidence": ""})
        self.assertGreater(full.total_input_tokens, instruction.total_input_tokens)
        self.assertEqual(full.omitted_blocks, [])
        self.assertEqual(full.truncated_blocks, [])

        self.set_budget(version, instruction.total_input_tokens + 1)
        with self.assertRaises(ContextOverflowError) as caught:
            ContextCompiler(version).compile({})
        message = str(caught.exception)
        self.assertIn("Context overflow", message)
        self.assertIn(str(full.total_input_tokens), message)
        self.assertIn(str(instruction.total_input_tokens + 1), message)
        self.assert_no_readiness_claim(message)

    def test_trim_budget_records_omitted_and_truncated_blocks(self):
        version = self.make_version(ContextRecipeVersion.BudgetPolicy.TRIM_LOWEST_PRIORITY)
        self.add_block(version, "instruction", "Keep.", priority=1, kind="instruction")
        self.add_block(
            version,
            "evidence",
            "evidence " * 40,
            priority=4,
            kind="evidence",
            max_tokens=6,
        )
        self.add_block(version, "history", "history " * 80, priority=9, kind="history")

        roomy = ContextCompiler(version).compile({})
        self.assertEqual(
            [block.block_key for block in roomy.included_blocks],
            ["instruction", "evidence", "history"],
        )
        self.assertEqual(roomy.omitted_blocks, [])
        self.assertEqual(len(roomy.truncated_blocks), 1)
        truncated = roomy.truncated_blocks[0]
        self.assertEqual(truncated["block_key"], "evidence")
        self.assertEqual(truncated["reason"], "block_token_limit")
        self.assertEqual(truncated["block_type"], "evidence")
        self.assertFalse(truncated["required"])
        self.assertTrue(truncated["included_in_final"])
        self.assertGreater(truncated["original_tokens"], truncated["tokens_retained"])
        self.assertLessEqual(truncated["tokens_retained"], 6)
        evidence = next(block for block in roomy.included_blocks if block.block_key == "evidence")
        self.assertTrue(evidence.truncated)
        self.assertLess(len(evidence.rendered_content), len(evidence.raw_content))

        kept = ContextCompiler(version).compile({"history": ""})
        self.assertEqual([block.block_key for block in kept.included_blocks], ["instruction", "evidence"])
        self.assertLess(kept.total_input_tokens, roomy.total_input_tokens)

        self.set_budget(version, kept.total_input_tokens)
        result = ContextCompiler(version).compile({})
        self.assertEqual(
            [block.block_key for block in result.included_blocks],
            ["instruction", "evidence"],
        )
        self.assertEqual([row["block_key"] for row in result.omitted_blocks], ["history"])
        omitted = result.omitted_blocks[0]
        self.assertEqual(omitted["reason"], "token_budget_overflow")
        self.assertEqual(omitted["block_type"], "history")
        self.assertEqual(omitted["priority"], 9)
        self.assertFalse(omitted["required"])
        self.assertGreater(omitted["tokens_omitted"], 0)
        self.assertEqual(result.truncated_blocks[0]["block_key"], "evidence")
        self.assertEqual(result.truncated_blocks[0]["reason"], "block_token_limit")
        self.assertTrue(result.truncated_blocks[0]["included_in_final"])
        self.assertFalse(result.truncated_blocks[0]["required"])
        accounted = {block.block_key for block in result.included_blocks}
        accounted.update(row["block_key"] for row in result.omitted_blocks)
        self.assertEqual(accounted, {"instruction", "evidence", "history"})
        self.assertNotIn("history", result.serialized_prompt)
        self.assertLessEqual(
            result.total_input_tokens + result.output_reserve_tokens,
            result.model_limit_tokens,
        )
        self.assert_no_readiness_claim(json.dumps(asdict(result)))

    def test_estimate_tokens_is_deterministic_for_the_same_input(self):
        samples = (
            "",
            "a",
            "Keep.",
            "evidence " * 40,
            "punctuation: a, b! (same)",
            "<|im_start|>user\nKeep.<|im_end|>",
        )
        for sample in samples:
            copy = "".join(sample)
            self.assertEqual(estimate_tokens(sample), estimate_tokens(copy))
            self.assertEqual(estimate_tokens(sample), estimate_tokens(sample))
            self.assertIsInstance(estimate_tokens(sample), int)
            self.assertGreaterEqual(estimate_tokens(sample), 0)
        self.assertEqual(estimate_tokens(""), 0)
        self.assertGreater(estimate_tokens("word"), 0)

        version = self.make_version(
            ContextRecipeVersion.BudgetPolicy.TRIM_LOWEST_PRIORITY,
            limit=80,
            reserve=4,
        )
        self.add_block(version, "instruction", "Keep.", priority=1, kind="instruction")
        self.add_block(version, "notes", "note " * 30, priority=8, kind="history")
        compiler = ContextCompiler(version)
        first = compiler.compile({})
        second = compiler.compile({})
        self.assertEqual(first.total_input_tokens, second.total_input_tokens)
        self.assertEqual(first.serialized_prompt, second.serialized_prompt)
        self.assertEqual(first.omitted_blocks, second.omitted_blocks)
        self.assertEqual(first.truncated_blocks, second.truncated_blocks)
        self.assertEqual(
            [block.rendered_content for block in first.included_blocks],
            [block.rendered_content for block in second.included_blocks],
        )

    def test_results_do_not_claim_qualified_or_production_ready(self):
        version = self.make_version(ContextRecipeVersion.BudgetPolicy.TRIM_OPTIONAL_EVIDENCE)
        self.add_block(version, "instruction", "Keep.", priority=1, kind="instruction")
        self.add_block(
            version,
            "evidence",
            "source " * 50,
            priority=6,
            kind="evidence",
            max_tokens=5,
        )
        self.add_block(version, "aside", "aside " * 20, priority=3, kind="history")
        roomy = ContextCompiler(version).compile({})
        self.assertTrue(roomy.truncated_blocks)
        kept = ContextCompiler(version).compile({"evidence": ""})
        self.assertLess(kept.total_input_tokens, roomy.total_input_tokens)
        self.set_budget(version, kept.total_input_tokens)
        result = ContextCompiler(version).compile({})
        self.assertEqual([block.block_key for block in result.included_blocks], ["instruction", "aside"])
        self.assertEqual(result.omitted_blocks[0]["block_key"], "evidence")
        self.assertEqual(result.omitted_blocks[0]["reason"], "token_budget_overflow")
        self.assertEqual(result.omitted_blocks[0]["block_type"], "evidence")
        self.assertFalse(result.truncated_blocks[0]["included_in_final"])
        payload = json.dumps(asdict(result))
        self.assert_no_readiness_claim(payload)
        self.assertNotIn("production ready", payload.lower())
