"""Golden-path download failures stop the run. They do not skip training."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

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
