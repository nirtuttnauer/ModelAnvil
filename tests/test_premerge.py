"""ANVIL-009: Node 24 pin and premerge fail-fast behavior."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import premerge  # noqa: E402


class PremergeTests(unittest.TestCase):
    def test_node_20_is_rejected(self):
        message = premerge.node_rejection("v20.19.0")
        self.assertIn("Node.js 24", message)
        self.assertIn("v20.19.0", message)
        self.assertIn("Node.js 20", message)

    def test_node_22_is_rejected(self):
        self.assertIn("v22.23.4", premerge.node_rejection("v22.23.4"))

    def test_node_24_is_accepted(self):
        self.assertIsNone(premerge.node_rejection("v24.11.0\n"))

    def test_missing_node_is_rejected(self):
        self.assertIn("Node.js 24", premerge.node_rejection(""))

    def test_python_312_only(self):
        self.assertIsNone(premerge.python_rejection((3, 12, 3)))
        self.assertIn("3.11", premerge.python_rejection((3, 11, 9)))
        self.assertIn("3.13", premerge.python_rejection((3, 13, 0)))

    def test_skip_xfail_and_timeout_fail(self):
        for field in ("skipped", "xfailed", "timeout"):
            run = premerge.zero_run("backend", "manage.py test")
            run[field] = 1
            message = premerge.runtime_problem([run])
            self.assertIsNotNone(message, field)
            self.assertIn(field if field != "skipped" else "skip", message)

    def test_clean_run_has_no_runtime_problem(self):
        run = premerge.zero_run("backend", "manage.py test")
        run["collected"] = 4
        run["passed"] = 4
        self.assertIsNone(premerge.runtime_problem([run]))

    def test_exclusions_match_ids(self):
        run = premerge.zero_run("backend", "manage.py test --exclude-tag=pg")
        premerge.apply_exclusions(run, ["modelanvil.rag.One", "modelanvil.rag.Two"])
        self.assertEqual(run["excluded_by_tag"], 2)
        self.assertEqual(run["excluded_ids"], ["modelanvil.rag.One", "modelanvil.rag.Two"])

    def test_django_skip_summary_fails_the_gate(self):
        text = "Ran 6 tests in 0.040s\n\nOK (skipped=1)\n"
        command = "python manage.py test --exclude-tag=pg"
        runs = premerge._rename(
            premerge._django_only(premerge.parse_runs(text, command)),
            "backend",
            command,
        )
        self.assertEqual(runs[0]["collected"], 6)
        self.assertEqual(runs[0]["skipped"], 1)
        self.assertEqual(runs[0]["passed"], 5)
        self.assertIsNotNone(premerge.runtime_problem(runs))

    def test_pg_display_command_omits_the_password_assignment(self):
        display = premerge.pg_display_command(sys.executable, Path("/tmp/modelanvil-premerge/cache"))
        self.assertNotIn("DATABASE_PASSWORD", display)
        self.assertIn("--tag=pg", display)
        self.assertIn("RABBITMQ_URL=", display)

    def test_node_20_process_fails_before_any_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp) / "bin"
            bindir.mkdir()
            node = bindir / "node"
            node.write_text("#!/bin/sh\necho v20.19.0\n", encoding="utf-8")
            node.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "premerge.py")],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("Node.js 24", completed.stderr)
        self.assertIn("v20.19.0", completed.stderr)
        self.assertNotIn("Ran ", completed.stdout)
        self.assertNotIn("docker", completed.stdout.lower())
        self.assertFalse((ROOT / "docs" / "engineering" / "verification" / "anvil-009-2026-10-29" / "premerge.json").exists())

    def test_pins_match_ci_images(self):
        self.assertEqual((ROOT / ".nvmrc").read_text().strip(), "24")
        self.assertEqual((ROOT / "web" / ".nvmrc").read_text().strip(), "24")
        package = json.loads((ROOT / "web" / "package.json").read_text())
        self.assertEqual(package["engines"]["node"], "24.x")
        compose = (ROOT / "compose.premerge.yaml").read_text()
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        for image in premerge.CI_IMAGES:
            self.assertIn(image, compose)
            self.assertIn(image, ci)
        for job in ("backend", "frontend", "pgvector"):
            self.assertIn(f"\n  {job}:\n", ci)


if __name__ == "__main__":
    unittest.main()
