#!/usr/bin/env python3
"""Fail-closed rendered Compose review for optional non-root API/worker rehearsal.

Print only fixed error categories: parsed Compose may contain credentials.
This command NEVER starts containers or alters Evidence files, ownership or ACLs.
It is NOT a customer rollout or an effective-UID access attestation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from pilot_compose_port_policy import verify as verify_private_ports

_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE = _ROOT / "docker-compose.yml"
_OVERLAY = _ROOT / "docker-compose.nonroot-optin.yml"
_SERVICES = ("preflight", "api", "worker")
_OWNER = "1000:1000"
_VOLUME = re.compile(r"(?:^|_)local_documents\\Z")


def verify_optin_rendered_compose(config: object) -> list[str]:
    """Verify effective identity/capability and existing Evidence mount contract."""
    if type(config) is not dict or type(config.get("services")) is not dict:
        return ["invalid_compose_services"]
    services = config["services"]
    errors: list[str] = []
    if verify_private_ports(config):
        errors.append("private_port_policy")
    for name in _SERVICES:
        service = services.get(name)
        if type(service) is not dict:
            errors.append(f"{name}:missing_service")
            continue
        if service.get("user") != _OWNER:
            errors.append(f"{name}:wrong_user")
        cap_drop = service.get("cap_drop")
        if (type(cap_drop) is not list or len(cap_drop) != 1
                or cap_drop[0] != "ALL"):
            errors.append(f"{name}:capabilities_not_dropped")
        options = service.get("security_opt")
        if (type(options) is not list or
                "no-new-privileges:true" not in options):
            errors.append(f"{name}:privilege_escalation_unrestricted")
        if service.get("privileged") is not False and service.get("privileged") is not None:
            errors.append(f"{name}:privileged_forbidden")
        for property_name in ("network_mode", "pid", "ipc", "userns_mode"):
            if service.get(property_name) == "host":
                errors.append(f"{name}:host_namespace_forbidden")
        if service.get("devices") or service.get("cap_add"):
            errors.append(f"{name}:extra_device_or_capability")
        volumes = service.get("volumes")
        if type(volumes) is not list or len(volumes) != 1:
            errors.append(f"{name}:evidence_mount_unexpected")
            continue
        mount = volumes[0]
        if (
            type(mount) is not dict
            or mount.get("type") != "volume"
            or type(mount.get("source")) is not str
            or _VOLUME.search(mount["source"]) is None
            or mount.get("target") != "/data/documents"
            or mount.get("read_only") is True
        ):
            errors.append(f"{name}:evidence_mount_unexpected")
    return errors


def render_optin_compose(*, env_file: Path) -> object:
    if not env_file.is_file() or not _COMPOSE.is_file() or not _OVERLAY.is_file():
        raise RuntimeError("config_unavailable")
    try:
        result = subprocess.run(
            [
                "docker", "compose", "--env-file", str(env_file),
                "-f", str(_COMPOSE), "-f", str(_OVERLAY),
                "config", "--format", "json",
            ],
            check=False, capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("compose_render_unavailable") from None
    if result.returncode:
        # Never print expanded Compose output or stderr; it can contain secrets.
        raise RuntimeError("compose_render_rejected")
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError("compose_json_invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-optin-nonroot-config", action="store_true")
    parser.add_argument("--env-file", type=Path, default=_ROOT / ".env.pilot.example")
    args = parser.parse_args(argv)
    if not args.verify_optin_nonroot_config:
        print("NO-GO: explicit_nonroot_review_flag_required", file=sys.stderr)
        return 2
    try:
        issues = verify_optin_rendered_compose(render_optin_compose(
            env_file=args.env_file,
        ))
    except RuntimeError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    if issues:
        for reason in issues:
            print("NO-GO: " + reason, file=sys.stderr)
        return 1
    print("CONFIG CHECK PASS: opt-in non-root Compose render has bounded identity and mounts.")
    print("NOT proof of runtime identity, actual Evidence access, volume ACLs or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
