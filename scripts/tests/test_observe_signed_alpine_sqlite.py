"""Offline tests: signed Alpine SQLite candidate observer must fail closed."""
import unittest

from scripts.observe_signed_alpine_sqlite import (
    ALPINE_READ_ONLY_SH, ARCHITECTURES, BASELINE, IMAGE,
    ObservationFailure, parse_candidate, render, validate_digest,
)

D = "sha256:" + "a" * 64


class SignedAlpineIndexTests(unittest.TestCase):
    def test_valid_single_entry_only(self):
        self.assertEqual(parse_candidate("sqlite-libs-3.53.4-r0"), BASELINE)
        for raw in ("", "sqlite-libs-3.53.4-r0\nsqlite-libs-3.54.1-r0",
                    "sqlite-libs-3.53.4-r0\nwarning: stale",
                    "sqlite-libs-3.54.1-r0 injected", "sqlite-3.54.1-r0"):
            with self.subTest(raw=raw), self.assertRaises(ObservationFailure):
                parse_candidate(raw)

    def test_missing_or_forged_digest_rejected(self):
        self.assertEqual(validate_digest("alpine@"+D), D)
        for digest in ("", "sha256:abc", "sha256:"+"b"*63+"g"):
            with self.subTest(digest=digest), self.assertRaises(ObservationFailure):
                validate_digest(digest)

    def test_all_architectures_required_and_no_false_clearance(self):
        valid = dict.fromkeys(ARCHITECTURES, BASELINE)
        output = render(valid, D)
        self.assertIn("NO NEW CANDIDATE", output)
        self.assertIn("NOT A FIX", output)
        self.assertIn("High", output.replace("HIGH", "High"))
        for results in ({}, {"x86_64": BASELINE},
                        {"x86_64": BASELINE, "aarch64": "not-a-version"}):
            with self.subTest(results=results), self.assertRaises(ObservationFailure):
                render(results, D)
        changed = render({"x86_64": "3.54.1-r0", "aarch64": BASELINE}, D)
        self.assertIn("SECURITY REVIEW REQUIRED", changed)
        self.assertIn("NOT A FIX", changed)

    def test_strict_sources_and_default_apk_signature_validation(self):
        self.assertEqual(IMAGE, "alpine:3.24")
        self.assertIn('test "$actual" = "$expected"', ALPINE_READ_ONLY_SH)
        self.assertIn("apk --arch", ALPINE_READ_ONLY_SH)
        self.assertIn("--update-cache search --exact sqlite-libs", ALPINE_READ_ONLY_SH)
        self.assertNotIn("--allow-untrusted", ALPINE_READ_ONLY_SH)
        self.assertNotIn("apk add ", ALPINE_READ_ONLY_SH)
        self.assertNotIn("apk upgrade", ALPINE_READ_ONLY_SH)


if __name__ == "__main__":
    unittest.main()
