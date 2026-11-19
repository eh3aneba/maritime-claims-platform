"""Synthetic-only regressions for private Persian OCR study-file custody."""
from __future__ import annotations

import contextlib
from io import StringIO
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts.persian_ocr_local_validation_metrics import _reject_duplicate_json_keys
from scripts.persian_ocr_private_study_input import (
    MAX_STUDY_BYTES, read_private_study_json,
)


def private_json(path: Path, text: str = '{"synthetic": true}') -> None:
    path.touch(mode=0o600, exist_ok=False)
    path.write_text(text, encoding="utf-8")


def read(path: Path) -> object:
    return read_private_study_json(
        path, object_pairs_hook=_reject_duplicate_json_keys,
    )


class PrivateOcrStudyInputTests(unittest.TestCase):
    def test_private_input_accepted_but_no_human_accuracy_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "study.json"
            private_json(path)
            self.assertEqual(read(path), {"synthetic": True})

    def test_stricter_inventory_cap_does_not_increase_global_limit(self):
        from scripts.persian_ocr_local_source_integrity import _read_json

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inventory.json"
            private_json(path)
            self.assertEqual(_read_json(path), {"synthetic": True})
            with self.assertRaises(ValueError):
                read_private_study_json(
                    path,
                    object_pairs_hook=_reject_duplicate_json_keys,
                    max_bytes=4,
                )
            for invalid_limit in (True, 0, -1, MAX_STUDY_BYTES + 1):
                with self.subTest(limit=invalid_limit), self.assertRaises(ValueError):
                    read_private_study_json(
                        path,
                        object_pairs_hook=_reject_duplicate_json_keys,
                        max_bytes=invalid_limit,
                    )

    @unittest.skipUnless(os.name == "posix", "POSIX permission enforcement")
    def test_group_and_world_access_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "study.json"
            private_json(path)
            for mode in (0o644, 0o640, 0o604, 0o666):
                path.chmod(mode)
                with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                    read(path)
            path.chmod(0o600)
            self.assertEqual(read(path), {"synthetic": True})

    def test_symlinks_nonregular_and_oversized_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "original.json"
            private_json(original)
            alias = root / "alias.json"
            try:
                alias.symlink_to(original)
            except (NotImplementedError, OSError):
                pass
            else:
                with self.assertRaises(ValueError):
                    read(alias)
            with self.assertRaises(ValueError):
                read(root)
            huge = root / "huge.json"
            huge.touch(mode=0o600, exist_ok=False)
            with huge.open("wb") as out:
                out.truncate(MAX_STUDY_BYTES + 1)
            with self.assertRaises(ValueError):
                read(huge)
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo"
                os.mkfifo(fifo, 0o600)
                with self.assertRaises(ValueError):
                    read(fifo)

    def test_nested_duplicate_keys_and_nonstandard_numbers_are_rejected(self):
        for index, content in enumerate((
            '{"a": 1, "a": 2}',
            '{"a": {"b": true, "b": false}}',
            '{"a": NaN}',
            '{"a": Infinity}',
            '{"a": -Infinity}',
            "PRIVATE_CLAIM_TRANSCRIPT",
        )):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "study.json"
                private_json(path, content)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    read(path)

    @unittest.skipUnless(os.name == "posix", "POSIX in-place mutation proof")
    def test_in_place_append_or_permission_change_during_read_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "study.json"
            private_json(path)
            actual_fstat = os.fstat
            for change in ("append", "chmod"):
                if change == "append":
                    path.write_text('{"synthetic": true}', encoding="utf-8")
                path.chmod(0o600)
                calls = []

                def at_second_fstat(fd):
                    calls.append(1)
                    if len(calls) == 2:
                        if change == "append":
                            with path.open("ab") as writer:
                                writer.write(b"synthetic-edit")
                        else:
                            path.chmod(0o644)
                    return actual_fstat(fd)

                with self.subTest(change=change), patch(
                    "scripts.persian_ocr_private_study_input.os.fstat",
                    side_effect=at_second_fstat,
                ):
                    with self.assertRaises(ValueError):
                        read(path)
                self.assertEqual(len(calls), 2)
            path.chmod(0o600)

    def test_all_three_cli_entrypoints_reject_public_private_inputs_without_echo(self):
        from scripts.persian_ocr_local_validation_metrics import main as metrics
        from scripts.persian_ocr_blind_cohort_preflight import main as cohort
        from scripts.persian_ocr_review_disagreement_metrics import main as reviews

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private.json"
            private_json(path, '{"sample":"PRIVATE_SOURCE_TEXT_DO_NOT_PRINT"}')
            if os.name == "posix":
                path.chmod(0o644)
            # Even on non-POSIX, a structurally invalid input is a failure.
            commands = (
                (metrics, ["--input", str(path)]),
                (cohort, ["--manifest", str(path), "--measurements", str(path)]),
                (reviews, ["--manifest", str(path), "--measurements", str(path),
                           "--reviews", str(path)]),
            )
            for cli, arguments in commands:
                stdout, stderr = StringIO(), StringIO()
                with self.subTest(cli=cli.__module__), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(cli(arguments), 2)
                self.assertNotIn("PRIVATE_SOURCE_TEXT_DO_NOT_PRINT", stdout.getvalue() + stderr.getvalue())
                self.assertNotIn(str(path), stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
