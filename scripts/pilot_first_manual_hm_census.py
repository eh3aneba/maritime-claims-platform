#!/usr/bin/env python3
"""Read-only, same-census Docker observation for FIRST manual synthetic H&M pilot.

Run on the independently selected isolated host. Reuses the existing strict
Compose config, Docker target, 11-service readiness, effective environment,
and running-image-ID controls with ONE before/after container census. It
never runs docker up/exec, changes state, emits credentials, authorizes
customer data, verifies a registry digest or grants a release approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__:
    from . import pilot_compose_readiness as readiness
    from . import pilot_demo_docker_target as target
    from . import pilot_rc_compose_feature_observation as rendered
    from . import pilot_rc_running_ai_env_readback as runtime
    from . import pilot_running_image_identity as images
else:
    import pilot_compose_readiness as readiness
    import pilot_demo_docker_target as target
    import pilot_rc_compose_feature_observation as rendered
    import pilot_rc_running_ai_env_readback as runtime
    import pilot_running_image_identity as images

SCHEMA = "mcri-pilot-first-manual-hm-census-v1"
SHA = re.compile(r"[a-f0-9]{40}\Z")


class SnapshotError(ValueError):
    """Code-owned error messages only; never raw environment or Docker data."""


def _private_env_file(path: Path) -> None:
    """No symlink or broadly readable operator dotenv may enter Docker."""
    if path.is_symlink() or not path.is_file():
        raise SnapshotError("private_env_not_regular")
    try:
        mode = path.stat().st_mode
    except OSError:
        raise SnapshotError("private_env_unavailable") from None
    if not stat.S_ISREG(mode):
        raise SnapshotError("private_env_not_regular")
    if os.name == "posix" and stat.S_IMODE(mode) & 0o077:
        raise SnapshotError("private_env_permissions_insecure")


def assess(*, config: object, before: list[dict], after: list[dict],
           environment_by_service: dict[str, list[str]],
           observed_images: dict[str, str], expected_images: dict[str, str],
           release_sha: str) -> dict:
    """Pure cross-gate check; all live reads must share the same census.

    A good record attests only bounded tool outputs, not real host integrity
    or truthful independent approval. Never serialize input payloads.
    """
    if type(release_sha) is not str or SHA.fullmatch(release_sha) is None:
        raise SnapshotError("invalid_release_sha")
    scope = rendered.inspect_config(config, release_sha=release_sha)
    if not scope["compose_ai_and_adapter_config_safe"]:
        raise SnapshotError("rendered_pilot_scope_rejected")

    before_ready = readiness.evaluate(before, release_sha=release_sha)
    after_ready = readiness.evaluate(after, release_sha=release_sha)
    effective = runtime.summarize(
        before=before, after=after, environment_by_service=environment_by_service,
        release_sha=release_sha, require_manual_hm_pilot=True,
    )
    identity = images.evaluate_images(
        before=before, after=after, observed_image_ids=observed_images,
        expected=expected_images, release_sha=release_sha,
    )
    checks = {
        "rendered_compose_manual_scope_safe": (
            scope["compose_ai_and_adapter_config_safe"] is True
            and scope["check_failures"] == []
        ),
        "same_census_service_status_complete": (
            before_ready["compose_status_complete"] is True
            and after_ready["compose_status_complete"] is True
        ),
        "effective_manual_hm_ai_ocr_adapters_off": (
            effective["manual_hm_runtime_scope_checked"] is True
            and effective["manual_hm_runtime_scope_safe_observed"] is True
            and effective["runtime_ai_config_disabled_observed"] is True
            and effective["check_failures"] == []
        ),
        "stable_container_image_ids_match_private_manifest": (
            identity["container_status_and_identity_stable"] is True
            and identity["all_running_image_ids_match_manifest"] is True
            and identity["expected_service_count"] == len(readiness.EXPECTED)
            and identity["matching_service_count"] == len(readiness.EXPECTED)
        ),
    }
    return {
        "schema": SCHEMA,
        "operator_supplied_release_sha": release_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "expected_service_count": len(readiness.EXPECTED),
        "checks": checks,
        "bounded_same_census_passed": all(checks.values()),
        # Even all four green technical checks cannot verify the operator,
        # OS, registry manifest digests, data-class scope or any release gate.
        "selected_host_independently_verified": False,
        "registry_digest_and_source_provenance_verified": False,
        "actual_network_egress_isolation_verified": False,
        "database_external_connectors_verified_disabled": False,
        "paired_evidence_postgres_recovery_verified": False,
        "rollback_and_alert_ownership_verified": False,
        "independent_security_and_hm_approvals_verified": False,
        "real_customer_data_authorized": False,
        "pilot_authorized": False,
    }


def observe(*, env_file: Path, manifest: Path, release_sha: str) -> dict:
    if type(release_sha) is not str or SHA.fullmatch(release_sha) is None:
        raise SnapshotError("invalid_release_sha")
    _private_env_file(env_file)
    # The startup guard rejects inherited remote Docker/Compose overrides.
    # Check it again for the later READ-ONLY operator observation.
    target.observe()
    expected = images.read_manifest(
        images._read_private_manifest(manifest), release_sha=release_sha,
    )
    config = rendered.observe_config(env_file=env_file)
    scope = rendered.inspect_config(config, release_sha=release_sha)
    if not scope["compose_ai_and_adapter_config_safe"]:
        raise SnapshotError("rendered_pilot_scope_rejected")

    before = readiness.observe(env_file=str(env_file))
    ids = runtime._observed_ids(before)
    effective = {name: runtime._read_config_env(cid) for name, cid in ids.items()}
    seen_images = images.inspect_image_ids(before)
    after = readiness.observe(env_file=str(env_file))
    return assess(
        config=config, before=before, after=after,
        environment_by_service=effective, observed_images=seen_images,
        expected_images=expected, release_sha=release_sha,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        record = observe(
            env_file=args.env_file, manifest=args.manifest,
            release_sha=args.release_sha,
        )
        images._write_private_record(args.output, record)
    except (SnapshotError, target.DockerTargetError,
            images.ImageIdentityError, runtime.RuntimeScopeError,
            readiness.ReadinessError, rendered.ComposeScopeError,
            OSError, ValueError, TypeError):
        print("NO-GO: first manual H&M same-census observation unavailable or unsafe",
              file=sys.stderr)
        return 2
    if not record["bounded_same_census_passed"]:
        print("NO-GO: first manual H&M observed container scope disagrees.")
        print("No credential, container identity or environment was disclosed.")
        return 1
    print("BOUNDED SAME-CENSUS READBACK PASS (synthetic first manual H&M scope).")
    print("NOT a verified host, registry digest, recovery, security clearance or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
