"""Observe official Alpine stable signed OpenSSL APK bytes without installing.

Issue #952 evidence only. Repository/package signature validation using the
pulled image's bundled trust keys does not authenticate the binary installed
in a production image, establish source-to-binary reproducibility, or grant
security approval. Never changes a production image or a required scan.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

IMAGE = "alpine:3.24"
VERSION = "3.5.9-r1"
PACKAGES = ("libcrypto3", "libssl3")
REPOSITORY = "https://dl-cdn.alpinelinux.org/alpine/v3.24/main"
ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
HASH_LINE = re.compile(r"([a-f0-9]{64})  (libcrypto3|libssl3)-3\.5\.9-r1\.apk\Z")

# Only scratch tmpfs is writable. Official stable main only; no key changes,
# no package installation, no --allow-untrusted or certificate exceptions.
SHELL = r"""
set -eu
test "$(uname -m)" = "$OBSERVE_ARCH"
test "$(apk --print-arch)" = "$OBSERVE_ARCH"
test -d /etc/apk/keys
test "$(find /etc/apk/keys -type f | wc -l)" -gt 0
mkdir /tmp/packages
printf '%s\n' 'https://dl-cdn.alpinelinux.org/alpine/v3.24/main' > /tmp/repos
apk --no-cache --repositories-file /tmp/repos fetch --output /tmp/packages \
    'libcrypto3=3.5.9-r1' 'libssl3=3.5.9-r1' >&2
cd /tmp/packages
test "$(find . -type f | wc -l)" -eq 2
for file in libcrypto3-3.5.9-r1.apk libssl3-3.5.9-r1.apk; do
    test -f "$file"
    test ! -L "$file"
    test -s "$file"
    apk verify "$file" >&2
    sha256sum "$file"
done
"""


class ObservationError(RuntimeError):
    """Only code-owned failure labels; not raw Docker output."""


def run(args: list[str], timeout: int, *, check_diagnostics: bool = False) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise ObservationError("bounded_docker_command_unavailable") from None
    if result.returncode != 0:
        raise ObservationError("docker_or_apk_rejected")
    if len(result.stdout) > 16_384 or len(result.stderr) > 64_000:
        raise ObservationError("oversized_observation_output")
    if check_diagnostics and re.search(
        r"(?i)\buntrusted\b|\bbad signature\b|warning:|error:|\bfailed\b|\binvalid signature\b",
        result.stderr,
    ):
        raise ObservationError("apk_signature_or_source_inconclusive")
    return result.stdout.strip()


def parse_image(output: str, architecture: str) -> tuple[str, str]:
    if architecture not in ARCH:
        raise ObservationError("unknown_architecture")
    fields = output.split("|")
    if len(fields) != 3:
        raise ObservationError("invalid_image_identity")
    image_id, image_arch, reference = fields
    prefix = "alpine@"
    if reference.startswith("docker.io/library/alpine@"):
        prefix = "docker.io/library/alpine@"
    if (
        image_arch != ARCH[architecture]
        or DIGEST.fullmatch(image_id) is None
        or not reference.startswith(prefix)
        or DIGEST.fullmatch(reference[len(prefix):]) is None
    ):
        raise ObservationError("invalid_image_identity")
    return image_id, reference[len(prefix):]


def parse_hashes(output: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in output.splitlines():
        match = HASH_LINE.fullmatch(line)
        if match is None:
            raise ObservationError("unexpected_package_observation")
        digest, package = match.groups()
        if package in hashes:
            raise ObservationError("duplicate_package_observation")
        hashes[package] = digest
    if set(hashes) != set(PACKAGES):
        raise ObservationError("incomplete_package_observation")
    return hashes


def observe(architecture: str) -> dict:
    if architecture not in ARCH:
        raise ObservationError("unknown_architecture")
    platform = "linux/" + ARCH[architecture]
    run(["docker", "pull", "--platform", platform, IMAGE], 180)
    image_id, digest = parse_image(run([
        "docker", "image", "inspect", "--format",
        "{{.Id}}|{{.Architecture}}|{{index .RepoDigests 0}}", IMAGE,
    ], 20), architecture)
    hashes = parse_hashes(run([
        "docker", "run", "--rm", "--read-only", "--platform", platform,
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "64", "--memory", "256m",
        "--env", f"OBSERVE_ARCH={architecture}",
        "--entrypoint", "/bin/sh",
        # Bind to the inspected local image ID, not the mutable pull tag.
        image_id, "-ec", SHELL,
    ], 120, check_diagnostics=True))
    return {
        "schema": "seeclaims-signed-openssl-package-observation-v1",
        "architecture": architecture,
        "repository": REPOSITORY,
        "package_version": VERSION,
        "trust_image_registry_digest": digest,
        "trust_image_local_id": image_id,
        "packages_sha256": hashes,
        "apk_verify_passed_using_image_trust_keys": True,
        "independent_trust_key_authentication_completed": False,
        "deployed_binary_matches_signed_apk": False,
        "source_patch_build_provenance_verified": False,
        "security_owner_approval": False,
        "pilot_authorized": False,
    }


def main() -> int:
    try:
        record = observe(os.environ.get("OBSERVE_ARCH", ""))
    except ObservationError as exc:
        print("INCONCLUSIVE: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(record, sort_keys=True))
    print("SIGNED APK OBSERVATION ONLY; NOT installed binary/source provenance, "
          "security approval, or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
