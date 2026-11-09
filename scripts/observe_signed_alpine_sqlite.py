"""Verify both Alpine v3.24 SQLite candidate indexes using apk's trusted keys.

Observation only. Never changes installed packages or production images. A
verified index is neither a signed fixed package, a CVE waiver, nor Grype PASS.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

IMAGE = "alpine:3.24"
ARCHITECTURES = ("x86_64", "aarch64")
BASELINE = "3.53.4-r0"
PACKAGE_LINE = re.compile(r"sqlite-libs-([0-9]+(?:\.[0-9]+){2,3}-r[0-9]+)\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REPOS = (
    "https://dl-cdn.alpinelinux.org/alpine/v3.24/main",
    "https://dl-cdn.alpinelinux.org/alpine/v3.24/community",
)
# Every active package source is compared against this exact allowlist; apk's
# default trusted keys must authenticate the index before package search.
ALPINE_READ_ONLY_SH = r"""
set -eu
test -d /etc/apk/keys
test "$(find /etc/apk/keys -type f -name '*.rsa.pub' | wc -l)" -ge 1
actual="$(grep -v '^#' /etc/apk/repositories | grep -v '^$')"
expected="https://dl-cdn.alpinelinux.org/alpine/v3.24/main
https://dl-cdn.alpinelinux.org/alpine/v3.24/community"
test "$actual" = "$expected"
apk --arch "$OBSERVE_ARCH" --no-cache --update-cache search --exact sqlite-libs
"""


class ObservationFailure(RuntimeError):
    pass


def parse_candidate(output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) != 1:
        raise ObservationFailure("Ambiguous or missing exact SQLite candidate")
    match = PACKAGE_LINE.fullmatch(lines[0].strip())
    if not match:
        raise ObservationFailure("Invalid SQLite candidate in signed APK index")
    return match.group(1)


def validate_digest(value: str) -> str:
    digest = value.rsplit("@", 1)[-1]
    if not DIGEST.fullmatch(digest):
        raise ObservationFailure("Image has no valid observed digest")
    return digest


def render(results: dict[str, str], image_digest: str) -> str:
    validate_digest(image_digest)
    if set(results) != set(ARCHITECTURES):
        raise ObservationFailure("Incomplete architecture verification")
    if any(
        not isinstance(value, str)
        or not PACKAGE_LINE.fullmatch(f"sqlite-libs-{value}")
        for value in results.values()
    ):
        raise ObservationFailure("Malformed candidate version")
    changed = any(value != BASELINE for value in results.values())
    rows = [
        "### Alpine 3.24 signed APKINDEX SQLite verification (read-only)",
        "",
        f"- Official Alpine image: `{IMAGE}` (observed digest `{image_digest}`)",
        "- Package manager: Alpine apk with image-bundled trusted public keys",
        "- Index source: official v3.24/main and v3.24/community only",
        "- apk did NOT use --allow-untrusted, alternate repositories, packages, or installs",
        "",
        "| Index architecture | Signed-repository sqlite-libs candidate |",
        "| --- | --- |",
    ]
    rows.extend(f"| `{arch}` | `{results[arch]}` |" for arch in ARCHITECTURES)
    rows.extend([
        "",
        ("**CANDIDATE CHANGED: SECURITY REVIEW REQUIRED**"
         if changed else "**NO NEW CANDIDATE: HIGH CVE HOLD REMAINS**"),
        "",
        "**NOT A FIX**: signature verification of repository metadata is not",
        "verification of a signed package's actual runtime installation, vendor CVE",
        "disposition, CLI CVE-2026-119586, or a clean final-image Grype scan.",
        "Keep API/Worker/Web real scans and 11 required checks fail-closed.",
        "No deployment, merge exception, CVE ignore, or pilot approval inferred.",
        "",
    ])
    return "\n".join(rows)


def run_bounded(args: list[str], seconds: int) -> tuple[str, str]:
    try:
        proc = subprocess.run(
            args, check=True, capture_output=True, text=True, timeout=seconds
        )
    except subprocess.CalledProcessError as err:
        detail = ((err.stderr or "") + "\n" + (err.stdout or ""))[-1400:]
        raise ObservationFailure(
            f"Docker/apk command {args[0]!r} exited {err.returncode}; diagnostic: {detail}"
        ) from err
    except (OSError, subprocess.TimeoutExpired) as err:
        raise ObservationFailure(
            f"Bounded Docker/apk command {args[0]!r} did not complete: {type(err).__name__}"
        ) from err
    if re.search(r"(?i)untrusted|bad signature|warning:|error:", proc.stderr):
        raise ObservationFailure("apk signature/source verification was inconclusive")
    return proc.stdout.strip(), proc.stderr.strip()


def main() -> int:
    try:
        run_bounded(["docker", "pull", IMAGE], 180)
        digest_raw, _ = run_bounded(
            ["docker", "image", "inspect", "--format",
             "{{index .RepoDigests 0}}", IMAGE], 20
        )
        digest = validate_digest(digest_raw)
        results = {}
        for arch in ARCHITECTURES:
            stdout, _ = run_bounded(
                [
                    "docker", "run", "--rm", "--read-only",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--pids-limit", "64", "--memory", "128m",
                    "--env", f"OBSERVE_ARCH={arch}",
                    "--entrypoint", "/bin/sh", IMAGE, "-ec",
                    ALPINE_READ_ONLY_SH,
                ], 90
            )
            results[arch] = parse_candidate(stdout)
        summary = render(results, digest)
    except ObservationFailure as exc:
        print(f"INCONCLUSIVE: {exc}", file=sys.stderr)
        return 2

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as out:
            out.write(summary)
    print(json.dumps({"apk_signed_index": True, "arch_versions": results,
                      "image_digest": digest, "security_fix": False}, sort_keys=True))
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
