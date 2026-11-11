"""Golden-path download failures stop the run. They do not skip training."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from scripts import golden_path


ROOT = Path(__file__).resolve().parents[3]


class GoldenPathCommandTests(SimpleTestCase):
    def test_readme_install_block_is_the_only_install(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(golden_path.install_commands(text), [
            "python3.12 -m venv .venv",
            ".venv/bin/python -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu",
            ".venv/bin/python -m pip install -r requirements.txt -r requirements.gpu.txt",
            "make migrate",
            ".venv/bin/python manage.py bootstrap_dev",
            "make check",
        ])
        train = golden_path.train_command(text, 3)
        self.assertEqual(train, (
            "MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false "
            ".venv/bin/python scripts/golden_path.py --train --steps 3"
        ))
        self.assertIn("--steps 2", golden_path.train_command(text, 2))
        self.assertNotIn("HF_TOKEN", train)
        self.assertNotIn("--ignore", "\n".join(golden_path.install_commands(text)))
        with self.assertRaises(ValueError):
            golden_path.train_command(text, 11)

    def test_refuses_more_than_ten_steps_and_a_non_sha(self):
        self.assertEqual(golden_path.main(["--train", "--steps", "11"]), 2)
        self.assertEqual(golden_path.main(["--train", "--steps", "0"]), 2)
        self.assertEqual(golden_path.main(["main"]), 2)
        self.assertEqual(golden_path.main(["--steps", "3"]), 2)

    def test_disabled_public_download_fails_before_training(self):
        with patch.dict("os.environ", {"MODELANVIL_PUBLIC_MODEL_DOWNLOADS": "0"}, clear=False), \
                patch.object(golden_path, "prepare_and_train") as train:
            self.assertEqual(golden_path.train_cli(3), 1)
            train.assert_not_called()


class GoldenPathDownloadTests(SimpleTestCase):
    def test_tampered_existing_files_fail_without_redownload_or_training(self):
        from modelanvil.runners.training.hf_runtime import FILE_HASHES

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in FILE_HASHES:
                (directory / name).write_bytes(b"tampered")
            with patch.object(golden_path, "_download_missing") as download, \
                    patch.object(golden_path, "run_steps") as train:
                with self.assertRaisesRegex(ValueError, "checksum changed"):
                    golden_path.prepare_and_train(directory, 1)
                download.assert_not_called()
                train.assert_not_called()

    def test_failed_download_does_not_train(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(golden_path, "_download_missing", side_effect=ConnectionError("download failed")), \
                    patch.object(golden_path, "run_steps") as train:
                with self.assertRaisesRegex(ConnectionError, "download failed"):
                    golden_path.prepare_and_train(directory, 2)
                train.assert_not_called()

    def test_downloaded_bytes_that_miss_the_pin_do_not_train(self):
        def write_bad(directory, names, source):
            for name in names:
                (directory / name).write_bytes(b"not-the-pinned-snapshot")

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(golden_path, "_download_missing", side_effect=write_bad), \
                    patch.object(golden_path, "run_steps") as train:
                with self.assertRaisesRegex(ValueError, "checksum changed"):
                    golden_path.prepare_and_train(directory, 1)
                train.assert_not_called()


class GoldenPathInferenceTests(SimpleTestCase):
    def _archive(self, root: Path) -> Path:
        import zipfile

        archive = root / "candidate.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("config.json", b"{}")
        return archive

    def test_both_consumers_are_separate_processes_and_return_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(Path(tmp))
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs.get("env")))
                script = Path(command[2]).name
                if script == "verify_cpu_export.py":
                    stdout = json.dumps({"generated_token_ids": [11, 12], "device": "cpu"})
                else:
                    stdout = json.dumps({
                        "generated_token_ids": [13],
                        "consumer_imported_modelanvil_or_django": False,
                    })
                return subprocess.CompletedProcess(command, 0, stdout, "")

            with patch.object(golden_path.subprocess, "run", side_effect=fake_run):
                result = golden_path.infer_exported_candidate(archive)
            self.assertEqual(result["verify_cpu_export"], [11, 12])
            self.assertEqual(result["hf_candidate_infer"], [13])
            self.assertEqual(len(calls), 2)
            verify_cmd, verify_env = calls[0]
            infer_cmd, infer_env = calls[1]
            self.assertEqual(verify_cmd[:2], [verify_cmd[0], "-I"])
            self.assertTrue(verify_cmd[2].endswith("scripts/verify_cpu_export.py"))
            self.assertEqual(verify_cmd[3:5], ["--archive", str(archive)])
            self.assertEqual(verify_cmd[5], "--sha256")
            self.assertEqual(len(verify_cmd[6]), 64)
            self.assertTrue(infer_cmd[2].endswith("scripts/hf_candidate_infer.py"))
            self.assertEqual(infer_cmd[infer_cmd.index("--device") + 1], "cpu")
            self.assertEqual(verify_env["HF_HUB_OFFLINE"], "1")
            self.assertEqual(verify_env["TRANSFORMERS_OFFLINE"], "1")
            self.assertNotIn("HF_TOKEN", verify_env)
            self.assertNotIn("HUGGING_FACE_HUB_TOKEN", verify_env)
            self.assertNotIn("PYTHONPATH", infer_env)
            self.assertIsNot(infer_env, os.environ)

    def test_missing_tokens_nonzero_exit_or_in_process_import_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(Path(tmp))

            def empty(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, json.dumps({"generated_token_ids": []}), "")

            with patch.object(golden_path.subprocess, "run", side_effect=empty):
                with self.assertRaisesRegex(RuntimeError, "did not return tokens"):
                    golden_path.infer_exported_candidate(archive)

            def crashed(command, **kwargs):
                return subprocess.CompletedProcess(command, 1, "", "")

            with patch.object(golden_path.subprocess, "run", side_effect=crashed) as run:
                with self.assertRaisesRegex(RuntimeError, "exited 1"):
                    golden_path.infer_exported_candidate(archive)
                self.assertEqual(run.call_count, 1)

            def imported(command, **kwargs):
                script = Path(command[2]).name
                if script == "verify_cpu_export.py":
                    stdout = json.dumps({"generated_token_ids": [1]})
                else:
                    stdout = json.dumps({
                        "generated_token_ids": [1],
                        "consumer_imported_modelanvil_or_django": True,
                    })
                return subprocess.CompletedProcess(command, 0, stdout, "")

            with patch.object(golden_path.subprocess, "run", side_effect=imported):
                with self.assertRaisesRegex(RuntimeError, "imported ModelAnvil or Django"):
                    golden_path.infer_exported_candidate(archive)


class GoldenPathOfflineTests(SimpleTestCase):
    @override_settings(MODELANVIL_PUBLIC_MODEL_DOWNLOADS=True, MODELANVIL_OFFLINE=False)
    def test_deleted_snapshot_and_blocked_network_fail_before_training(self):
        from modelanvil.runners.training.hf_runtime import FILE_HASHES, LIMITS

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "smollm2-135m"
            directory.mkdir()
            for name in FILE_HASHES:
                (directory / name).write_bytes(b"cached-snapshot")
            for path in list(directory.iterdir()):
                path.unlink()
            self.assertEqual(list(directory.iterdir()), [])
            cache = root / "hub-cache"
            cache.mkdir()
            env = {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "HF_HOME": str(root / "hf-home"),
                "HF_HUB_CACHE": str(cache),
                "HUGGINGFACE_HUB_CACHE": str(cache),
                "MODELANVIL_PUBLIC_MODEL_DOWNLOADS": "1",
            }

            def blocked(*args, **kwargs):
                raise OSError("network blocked")

            with patch.dict(os.environ, env, clear=False), \
                    patch("socket.create_connection", side_effect=blocked), \
                    patch("socket.socket.connect", side_effect=blocked), \
                    patch("time.sleep", return_value=None), \
                    patch.object(golden_path, "run_steps") as train:
                try:
                    import huggingface_hub.constants as hf_constants
                except ImportError:
                    hf_constants = None
                started = []
                if hf_constants is not None:
                    started.append(patch.object(hf_constants, "HF_HUB_OFFLINE", True))
                    if hasattr(hf_constants, "HF_HUB_CACHE"):
                        started.append(patch.object(hf_constants, "HF_HUB_CACHE", str(cache)))
                    if hasattr(hf_constants, "HF_HUB_DISABLE_XET"):
                        started.append(patch.object(hf_constants, "HF_HUB_DISABLE_XET", True))
                for item in started:
                    item.start()
                try:
                    with self.assertRaises(Exception):
                        golden_path.prepare_and_train(directory, 1)
                finally:
                    for item in reversed(started):
                        item.stop()
                train.assert_not_called()
                with self.assertRaises(ValueError):
                    golden_path.verify_snapshot(directory, FILE_HASHES, LIMITS)
