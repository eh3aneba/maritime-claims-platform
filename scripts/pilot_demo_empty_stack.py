#!/usr/bin/env python3
"""Read-only fail-closed check: no prior Compose state before synthetic MT ORION seed.

This checks only the *selected* Compose project and its rendered named volumes.
It cannot prove the host is empty, identify all foreign stores, or authorize
release, external evidence, production use, or customer data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from pilot_compose_port_policy import render_compose

EXPECTED_VOLUMES = frozenset(("postgres_data", "clamav_data", "local_documents"))
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
MAX_OUTPUT = 2 * 1024 * 1024


class ExistingStackError(ValueError):
    """Fixed, privacy-safe diagnostic; never includes Docker output or names."""


def _parse_containers(raw: str) -> list[dict]:
    if not isinstance(raw, str) or len(raw) > MAX_OUTPUT:
        raise ExistingStackError("invalid Compose container response")
    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except ValueError:
        try:
            payload = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except ValueError:
            raise ExistingStackError("invalid Compose container response") from None
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or any(not isinstance(x, dict) for x in payload):
        raise ExistingStackError("invalid Compose container response")
    return payload


def verify(config: object, containers: object, volume_names: object) -> None:
    if not isinstance(config, dict) or not isinstance(config.get("name"), str):
        raise ExistingStackError("rendered Compose project identity unavailable")
    if not NAME.fullmatch(config["name"]):
        raise ExistingStackError("invalid rendered Compose project identity")
    defs = config.get("volumes")
    if not isinstance(defs, dict) or set(defs) != EXPECTED_VOLUMES:
        raise ExistingStackError("expected isolated named Compose volumes unavailable")
    expected: set[str] = set()
    for key in EXPECTED_VOLUMES:
        item = defs[key]
        if not isinstance(item, dict) or item.get("external") is True:
            raise ExistingStackError("external or malformed Compose volume prohibited")
        volume_name = item.get("name")
        if not isinstance(volume_name, str) or not NAME.fullmatch(volume_name):
            raise ExistingStackError("rendered Compose volume name unavailable")
        if volume_name != config["name"] + "_" + key:
            raise ExistingStackError("unexpected Compose volume namespace")
        expected.add(volume_name)
    if len(expected) != len(EXPECTED_VOLUMES):
        raise ExistingStackError("Compose volume names are not unique")
    if not isinstance(containers, list) or any(not isinstance(x, dict) for x in containers):
        raise ExistingStackError("invalid Compose container status")
    if containers:
        raise ExistingStackError("Compose project already contains containers")
    if not isinstance(volume_names, list) or any(
        not isinstance(x, str) or not NAME.fullmatch(x) for x in volume_names
    ):
        raise ExistingStackError("invalid Docker volume inventory")
    if any(x in expected for x in volume_names):
        raise ExistingStackError("synthetic Compose project has pre-existing data volumes")


def _command(args: list[str]) -> str:
    try:
        p = subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ExistingStackError("Docker read-only inventory unavailable") from None
    if p.returncode != 0 or len(p.stdout) > MAX_OUTPUT:
        raise ExistingStackError("Docker read-only inventory failed")
    return p.stdout


def observe(*, env_file: Path) -> None:
    # Rendered config may include expanded private secrets. Never print it.
    try:
        config = render_compose(env_file=env_file, compose_file=Path("docker-compose.yml"))
    except RuntimeError:
        raise ExistingStackError("rendered Compose configuration unavailable") from None
    raw_ps = _command([
        "docker", "compose", "--env-file", str(env_file),
        "ps", "--all", "--format", "json",
    ])
    containers = _parse_containers(raw_ps)
    raw_volumes = _command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    volumes = [line.strip() for line in raw_volumes.splitlines() if line.strip()]
    verify(config, containers, volumes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", required=True, type=Path)
    args = p.parse_args(argv)
    try:
        observe(env_file=args.env_file)
    except ExistingStackError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    print("SYNTHETIC COMPOSE PROJECT EMPTY: no existing target containers or named volumes.")
    print("Host/foreign volumes, custody and Pilot GO remain UNVERIFIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
