"""Synthetic static regression for the stable OpenSSL security floor in final images.

This is a fail-closed source-policy check, not package-signature validation,
a vulnerability scan, a runtime attestation, or customer Pilot authorization.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_CONSTRAINTS = ("'libssl3>=3.5.9-r1'", "'libcrypto3>=3.5.9-r1'")
_REQUIRED_UPGRADE = "apk upgrade --no-cache libssl3 libcrypto3 zlib"


def _stages(source: str) -> dict[str, str]:
    heads = list(
        re.finditer(
            r"(?m)^FROM\s+[^\n]+\s+AS\s+([A-Za-z0-9_-]+)\s*$",
            source,
        )
    )
    if not heads:
        raise AssertionError("Dockerfile contains no named build stages")
    return {
        head.group(1): source[
            head.end() : heads[index + 1].start() if index + 1 < len(heads) else len(source)
        ]
        for index, head in enumerate(heads)
    }


def _require_stable_openssl_floor(stage: str) -> None:
    # Remove standalone comments so a commented-out constraint cannot pass.
    active = "\n".join(
        line for line in stage.splitlines() if not line.lstrip().startswith("#")
    )
    active = active.replace("\\\n", " ")
    if _REQUIRED_UPGRADE not in active:
        raise AssertionError("Final runtime stage has no stable package upgrade")
    installs = re.findall(r"(?:/sbin/)?apk add --no-cache\s+([^\n;&]+)", active)
    if not any(
        all(token in install.split() for token in _REQUIRED_CONSTRAINTS)
        for install in installs
    ):
        raise AssertionError("Final image missing patched stable OpenSSL dependency floors")


class StableOpenSSLFinalImagePolicyTests(unittest.TestCase):
    def test_final_api_worker_and_web_stages_enforce_stable_floors(self) -> None:
        expected = (
            ("apps/api/Dockerfile", ("base", "worker")),
            ("apps/web/Dockerfile", ("runner",)),
        )
        for path, names in expected:
            stages = _stages((_ROOT / path).read_text(encoding="utf-8"))
            for name in names:
                with self.subTest(path=path, stage=name):
                    self.assertIn(name, stages, "Expected final runtime stage missing")
                    _require_stable_openssl_floor(stages[name])

    def test_downgrade_or_missing_package_floor_fails_closed(self) -> None:
        stages = _stages((_ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8"))
        original = stages["base"]
        _require_stable_openssl_floor(original)
        for token in _REQUIRED_CONSTRAINTS:
            with self.subTest(token=token):
                weakened = original.replace(token, token.replace("3.5.9-r1", "3.5.9-r0"))
                self.assertNotEqual(weakened, original)
                with self.assertRaisesRegex(AssertionError, "dependency floors"):
                    _require_stable_openssl_floor(weakened)

    def test_disabled_or_missing_upgrade_fails_closed(self) -> None:
        stages = _stages((_ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8"))
        original = stages["runner"]
        _require_stable_openssl_floor(original)
        with self.assertRaisesRegex(AssertionError, "upgrade"):
            _require_stable_openssl_floor(
                original.replace(_REQUIRED_UPGRADE, "apk info -v libssl3 libcrypto3")
            )
        with self.assertRaisesRegex(AssertionError, "dependency floors"):
            _require_stable_openssl_floor(
                original.replace(
                    "'libcrypto3>=3.5.9-r1'",
                    "",
                )
            )


if __name__ == "__main__":
    unittest.main()
