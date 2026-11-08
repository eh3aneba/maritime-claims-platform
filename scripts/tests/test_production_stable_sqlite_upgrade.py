"""Fail-closed source-policy guard for signed stable SQLite runtime updates.

Only verifies production Dockerfile wiring and unchanged scanner policy.
Passing this test is NOT an image vulnerability scan or CVE clearance.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps" / "api" / "Dockerfile"
WORKFLOW = ROOT / ".github" / "workflows" / "supply-chain.yml"
GRYPE = ROOT / ".grype.yaml"


def _stage(dockerfile: str, name: str) -> str:
    stage = re.search(
        rf"^FROM python:3\.14\.10-alpine3\.24 AS {re.escape(name)}\s*$"
        r"(?P<body>.*?)(?=^FROM |\Z)",
        dockerfile,
        re.MULTILINE | re.DOTALL,
    )
    if not stage:
        raise AssertionError(f"Expected supported production {name} stage")
    return stage.group("body")



# Literal source-policy check, not a shell/dataflow proof. Inspect ALL lines,
# including continued RUN arguments and script copies, instead of only the
# first physical RUN line.
_FORBIDDEN_APK_SOURCE_PATTERNS = (
    r"(?i)(?<![\w-])--repository(?:[=\s]|$)",
    r"(?i)(?<![\w-])-X(?:[=\s]|$)",
    r"(?i)(?<![\w-])--allow-untrusted\b",
    r"(?i)(?<![\w-])--insecure\b",
    r"(?i)(?<![\w-])--no-check-certificate\b",
    r"(?i)/etc/apk/repositories",
    r"(?i)(?:dl-cdn\.)?alpinelinux\.org/alpine/(?!v3\.24(?:/|$))[\w.]+",
)


def _forbidden_apk_source(text: str) -> str | None:
    for pattern in _FORBIDDEN_APK_SOURCE_PATTERNS:
        if re.search(pattern, text):
            return pattern
    return None


class StableSqliteRuntimePolicyTests(unittest.TestCase):
    def test_both_runtime_images_upgrade_sqlite_from_supported_sources(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        for name in ("base", "worker"):
            with self.subTest(stage=name):
                stage = _stage(text, name)
                self.assertIn(
                    "/sbin/apk upgrade --no-cache libssl3 libcrypto3 zlib sqlite-libs",
                    stage,
                )
                self.assertIn(
                    "/sbin/apk info -v libssl3 libcrypto3 zlib sqlite-libs", stage,
                )
                self.assertIn("! command -v sqlite3", stage)
                self.assertIn("import ", stage)
                self.assertIn("sqlite3.sqlite_version", stage)

    def test_no_unapproved_repositories_or_unsigned_apk_inputs(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        # The pinned official Alpine runtime's signed v3.24 repositories
        # remain the sole APK input; alternate sources fail closed.
        self.assertIsNone(_forbidden_apk_source(text))

    def test_repository_override_on_continued_lines_is_rejected(self) -> None:
        for injected in (
            "RUN apk add \\\n    --repository https://dl-cdn.alpinelinux.org/alpine/edge/main sqlite-libs",
            "RUN apk add \\\n    -X https://mirror.invalid/alpine/staging sqlite-libs",
            "RUN printf '%s\\n' edge >> /etc/apk/repositories",
            "RUN apk add --allow-untrusted /tmp/sqlite-libs.apk",
        ):
            with self.subTest(injected=injected.splitlines()[0]):
                self.assertIsNotNone(_forbidden_apk_source(injected))
        self.assertIsNone(
            _forbidden_apk_source(
                "RUN /sbin/apk upgrade --no-cache libssl3 libcrypto3 zlib sqlite-libs"
            )
        )

    def test_mandatory_high_scanning_remains_enforced(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Container image vulnerability scan", workflow)
        self.assertEqual(workflow.count("severity-cutoff: high"), 3)
        self.assertEqual(workflow.count("fail-build: true"), 3)
        self.assertIn('test "${API_SCAN_OUTCOME}" = "success"', workflow)
        self.assertIn('test "${WEB_SCAN_OUTCOME}" = "success"', workflow)
        self.assertIn('test "${WORKER_SCAN_OUTCOME}" = "success"', workflow)
        self.assertEqual(GRYPE.read_text(encoding="utf-8").strip(), "ignore: []")

    def test_no_risk_acceptance_from_source_policy_check(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertNotIn("sqlite-libs=3.54.1-r0", text)
        self.assertNotIn("sqlite-libs@edge", text)
        self.assertNotIn("apk del --force", text)


if __name__ == "__main__":
    unittest.main()
