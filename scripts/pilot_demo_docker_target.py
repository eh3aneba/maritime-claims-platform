#!/usr/bin/env python3
"""Read-only local Docker Engine boundary for synthetic MT ORION demo startup.

Does not attest the ownership of a Unix socket/npipe, host isolation or the
absence of foreign data. Prevents accidental SSH/TCP context or inherited
Compose project/override redirection before side-effecting Docker commands.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

# These host environment settings can change the Compose project identity,
# resolve different YAML/files or redirect Docker to another daemon.
BLOCKED = frozenset({
    "DOCKER_HOST", "DOCKER_CONTEXT",
    "COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES",
    "COMPOSE_ENV_FILES", "COMPOSE_DISABLE_ENV_FILE",
    "COMPOSE_PROJECT_DIRECTORY", "COMPOSE_PATH_SEPARATOR",
    "COMPOSE_IGNORE_ORPHANS", "COMPOSE_REMOVE_ORPHANS",
})


class DockerTargetError(ValueError):
    """Fixed safe error text, never echoes private endpoint or Docker output."""


def verify(env: dict[str, str], context: object) -> None:
    if any(key in env for key in BLOCKED):
        raise DockerTargetError("Docker/Compose destination override is set")
    if not isinstance(context, list) or len(context) != 1:
        raise DockerTargetError("Docker context response incomplete")
    entry = context[0]
    if not isinstance(entry, dict):
        raise DockerTargetError("Docker context response malformed")
    endpoints = entry.get("Endpoints")
    if not isinstance(endpoints, dict) or not isinstance(endpoints.get("docker"), dict):
        raise DockerTargetError("Docker Engine endpoint missing")
    endpoint = endpoints["docker"]
    target = endpoint.get("Host")
    if not isinstance(target, str) or len(target) > 1024:
        raise DockerTargetError("Docker Engine endpoint missing")
    try:
        parsed = urlsplit(target)
    except ValueError:
        raise DockerTargetError("Docker Engine endpoint invalid") from None
    if (parsed.scheme not in {"unix", "npipe"}
            or parsed.netloc
            or not parsed.path.startswith("/")
            or parsed.query or parsed.fragment
            or any(ord(c) < 32 for c in target)):
        raise DockerTargetError("Docker Engine endpoint is not a local socket/pipe")
    if parsed.scheme == "unix" and (
        not target.startswith("unix:///") or ".." in parsed.path.split("/")
    ):
        raise DockerTargetError("Docker Engine Unix socket path unsafe")


def observe() -> None:
    # Docker context inspect is read-only. Never print its output.
    try:
        result = subprocess.run(
            ["docker", "context", "inspect"],
            capture_output=True, check=False, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DockerTargetError("Docker context inspection unavailable") from None
    if result.returncode != 0 or len(result.stdout) > 65536:
        raise DockerTargetError("Docker context inspection failed")
    try:
        raw = json.loads(result.stdout)
    except ValueError:
        raise DockerTargetError("Docker context response invalid") from None
    verify(dict(os.environ), raw)


def main() -> int:
    try:
        observe()
    except DockerTargetError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    print("LOCAL DOCKER ENDPOINT CHECK PASS: context uses local socket or pipe.")
    print("Engine ownership, underlying host isolation and Pilot GO remain UNVERIFIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
