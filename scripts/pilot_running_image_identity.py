#!/usr/bin/env python3
"""Read-only local Pilot Docker container-image ID readback.

Compares running containers with an independently prepared local manifest of
immutable Docker IMAGE IDs, not registry manifest digests. Neither the
operator-supplied release SHA nor the image-to-source provenance is attested.
No writes to Docker; never expose raw container metadata, IDs or credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

from pilot_compose_readiness import EXPECTED, ReadinessError, evaluate, observe

SHA = re.compile(r"[a-f0-9]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")
CONTAINER_ID = re.compile(r"[a-f0-9]{12,64}\Z")
SCHEMA = "mcri-pilot-running-images-v1"


class ImageIdentityError(ValueError):
    """Sanitized failure with no raw host/container/image strings."""


def manifest_template(release_sha: str) -> dict:
    if not isinstance(release_sha, str) or not SHA.fullmatch(release_sha):
        raise ImageIdentityError("invalid candidate source SHA")
    return {
        "schema": SCHEMA,
        "candidate_release_sha": release_sha,
        "expected_image_ids": {service: "" for service in EXPECTED},
    }


def read_manifest(raw: object, *, release_sha: str) -> dict[str, str]:
    if (not isinstance(raw, dict)
            or set(raw) != set(manifest_template(release_sha))
            or raw.get("schema") != SCHEMA
            or raw.get("candidate_release_sha") != release_sha):
        raise ImageIdentityError("expected manifest identity incomplete")
    expected = raw.get("expected_image_ids")
    if not isinstance(expected, dict) or set(expected) != set(EXPECTED):
        raise ImageIdentityError("expected service image map incomplete")
    if any(not isinstance(x, str) or not IMAGE_ID.fullmatch(x)
           for x in expected.values()):
        raise ImageIdentityError("expected immutable Docker image ID invalid")
    return expected


def _service_ids(items: object) -> dict[str, str]:
    if not isinstance(items, list):
        raise ImageIdentityError("invalid Compose service list")
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ImageIdentityError("invalid service status")
        name = item.get("Service")
        if name == "demo-seed":
            continue
        if name not in EXPECTED or name in result:
            raise ImageIdentityError("unexpected or duplicated Compose service")
        container_id = item.get("ID")
        if (not isinstance(container_id, str)
                or not CONTAINER_ID.fullmatch(container_id)):
            raise ImageIdentityError("container identity unavailable")
        result[name] = container_id
    if set(result) != set(EXPECTED) or len(set(result.values())) != len(EXPECTED):
        raise ImageIdentityError("missing or reused container identity")
    return result


def evaluate_images(*, before: list[dict], after: list[dict],
                    observed_image_ids: dict[str, str], expected: dict[str, str],
                    release_sha: str) -> dict:
    readiness_before = evaluate(before, release_sha=release_sha)
    readiness_after = evaluate(after, release_sha=release_sha)
    if not readiness_before["compose_status_complete"] or not readiness_after["compose_status_complete"]:
        raise ImageIdentityError("Compose readiness changed or incomplete")
    ids_before = _service_ids(before)
    ids_after = _service_ids(after)
    if ids_before != ids_after:
        raise ImageIdentityError("container identity changed during observation")
    if set(observed_image_ids) != set(EXPECTED):
        raise ImageIdentityError("observed service-image set incomplete")
    expected = read_manifest(manifest_template(release_sha) | {
        "expected_image_ids": expected,
    }, release_sha=release_sha)
    matches = {}
    for service in EXPECTED:
        observed = observed_image_ids[service]
        if not isinstance(observed, str) or not IMAGE_ID.fullmatch(observed):
            raise ImageIdentityError("invalid runtime Docker image ID")
        matches[service] = observed == expected[service]
    return {
        "schema": "mcri-pilot-running-image-readback-v1",
        "operator_supplied_candidate_release_sha": release_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "expected_service_count": len(EXPECTED),
        "matching_service_count": sum(matches.values()),
        "services": {service: {"image_id_matches": matches[service]} for service in EXPECTED},
        "container_status_and_identity_stable": True,
        "all_running_image_ids_match_manifest": all(matches.values()),
        "expected_manifest_provenance_independently_verified": False,
        "registry_image_digest_verified": False,
        "source_sha_to_image_verified": False,
        "fresh_host_deployment_verified": False,
        "independent_operator_verified": False,
        "pilot_authorized": False,
    }


def _inspect_one(container_id: str) -> str:
    if not CONTAINER_ID.fullmatch(container_id):
        raise ImageIdentityError("invalid container identity")
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--type", "container", container_id],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ImageIdentityError("container inspect unavailable") from None
    if proc.returncode != 0 or len(proc.stdout) > 2 * 1024 * 1024:
        raise ImageIdentityError("container inspect failed")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise ImageIdentityError("container inspect response malformed") from None
    if (not isinstance(data, list) or len(data) != 1
            or not isinstance(data[0], dict)
            or not isinstance(data[0].get("Id"), str)
            or not data[0]["Id"].startswith(container_id)):
        raise ImageIdentityError("inspected container identity mismatch")
    image = data[0].get("Image")
    if not isinstance(image, str) or not IMAGE_ID.fullmatch(image):
        raise ImageIdentityError("inspected container image ID invalid")
    return image


def inspect_image_ids(items: list[dict]) -> dict[str, str]:
    ids = _service_ids(items)
    return {service: _inspect_one(ids[service]) for service in EXPECTED}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.init:
            result = manifest_template(args.release_sha)
        else:
            if not args.manifest or not args.manifest.is_file():
                raise ImageIdentityError("approved local manifest unavailable")
            if args.manifest.stat().st_size > 16384:
                raise ImageIdentityError("oversized local image manifest")
            with args.manifest.open(encoding="utf-8") as stream:
                manifest = json.load(stream)
            expected = read_manifest(manifest, release_sha=args.release_sha)
            before = observe(env_file=args.env_file)
            observed = inspect_image_ids(before)
            after = observe(env_file=args.env_file)
            result = evaluate_images(
                before=before, after=after, observed_image_ids=observed,
                expected=expected, release_sha=args.release_sha,
            )
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (ImageIdentityError, ReadinessError):
        print("NO-GO: running image identity verification unavailable or failed", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print("NO-GO: local image record unavailable or cannot be written", file=sys.stderr)
        return 2
    if args.init:
        print("NO-GO: empty image-ID comparison template created; no Docker readback.")
        return 0
    if not result["all_running_image_ids_match_manifest"]:
        print("NO-GO: one or more running image IDs differ from the approved manifest.")
        return 1
    print("11/11 live Docker container image IDs match operator manifest.")
    print("Source SHA provenance, registry digests, host and Pilot GO remain UNPROVEN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
