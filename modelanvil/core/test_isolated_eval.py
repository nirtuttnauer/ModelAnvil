"""The isolated eval harness cuts egress without pretending an env var is a network."""
from pathlib import Path
import ast
import re

from django.core.management import get_commands
from django.test import SimpleTestCase

from modelanvil.rag.benchmark_corpus import cache_corpus
from modelanvil.rag.embedding_model import cache_pinned_model


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.isolated-eval.yaml"
HARNESS = ROOT / "scripts" / "isolated_eval.py"
ASSIGNMENT = re.compile(r"(?m)^\s*(HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE)\s*:")


class IsolatedEvalNetworkTests(SimpleTestCase):
    def test_compose_network_has_no_egress_and_does_not_publish_ports(self):
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("internal: true", text)
        self.assertIn("networks: [isolated]", text)
        self.assertNotIn("ports:", text)
        self.assertIsNone(ASSIGNMENT.search(text))
        self.assertIn("pgvector/pgvector:pg16", text)
        self.assertIn("RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672/%2F", text)

    def test_harness_prefetches_then_runs_eval_and_an_empty_cache(self):
        source = HARNESS.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"prefetch", "run_suite", "curl_from_eval", "cache_files"} <= functions)
        for name in ("cache_pinned_model", "cache_corpus", "cache_rag_decoder", "https://huggingface.co"):
            self.assertIn(name, source)
        self.assertIn('"--exclude-tag=pg"', source)
        self.assertIn('"--tag=pg"', source)
        self.assertNotIn("HF_HUB_OFFLINE=", source)
        self.assertNotIn("TRANSFORMERS_OFFLINE=", source)

    def test_prefetch_entry_points_are_the_operator_commands(self):
        self.assertTrue(callable(cache_pinned_model))
        self.assertTrue(callable(cache_corpus))
        self.assertIn("cache_rag_decoder", get_commands())
