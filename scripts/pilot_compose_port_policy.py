#!/usr/bin/env python3
"""Fail-closed host-port check for the private MCRI pilot Docker Compose stack.

This inspects Docker Compose's *rendered* configuration, not regex matches
against source YAML. It never launches containers, echoes the rendered
configuration, prints secrets, or grants release/pilot authorization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

# The private single-workstation pilot is not a public deployment.
_EXPECTED = {"db": 5432, "api": 8000, "web": 3000}
_LOOPBACK = "127.0.0.1"
_DECIMAL_PORT = re.compile(r"(?:[1-9][0-9]{0,4})\Z")


def _port_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 65535 else None
    if isinstance(value, str) and _DECIMAL_PORT.fullmatch(value):
        number = int(value)
        return number if number <= 65535 else None
    return None


def verify(config: object) -> list[str]:
    """Allow exactly three loopback-only mappings; deny all other exposures."""
    if not isinstance(config, dict) or not isinstance(config.get("services"), dict):
        return ["Docker Compose configuration is missing its services map"]
    services = config["services"]
    issues: list[str] = []
    for service in _EXPECTED:
        if service not in services:
            issues.append(f"{service}: required service missing")
    for name, definition in services.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            issues.append("Invalid Compose service definition")
            continue
        if definition.get("network_mode") == "host":
            issues.append(f"{name}: host networking is forbidden for private pilot")
        ports = definition.get("ports", [])
        if not isinstance(ports, list):
            issues.append(f"{name}: malformed ports configuration")
            continue
        expected_port = _EXPECTED.get(name)
        actual: list[tuple[int, int]] = []
        for port in ports:
            if not isinstance(port, dict):
                issues.append(f"{name}: unparsed or unsupported port mapping")
                continue
            host_ip = port.get("host_ip")
            target = _port_number(port.get("target"))
            published = _port_number(port.get("published"))
            protocol = port.get("protocol", "tcp")
            if host_ip != _LOOPBACK:
                issues.append(f"{name}: port binding is not IPv4 loopback-only")
            if protocol != "tcp":
                issues.append(f"{name}: non-TCP published port is forbidden")
            if target is None or published is None:
                issues.append(f"{name}: invalid or dynamic published port")
                continue
            actual.append((target, published))
            if expected_port is None or (target, published) != (expected_port, expected_port):
                issues.append(f"{name}: unexpected published port mapping")
        if expected_port is not None and actual != [(expected_port, expected_port)]:
            issues.append(f"{name}: expected exactly one approved loopback port")
    return issues


def render_compose(*, env_file: Path, compose_file: Path) -> object:
    if not env_file.is_file() or not compose_file.is_file():
        raise RuntimeError("Compose or environment file is unavailable")
    try:
        proc = subprocess.run(
            ["docker", "compose", "--env-file", str(env_file),
             "-f", str(compose_file), "config", "--format", "json"],
            check=False, capture_output=True, text=True, timeout=40,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Docker Compose configuration validation unavailable") from None
    if proc.returncode:
        # Never copy subprocess stderr/stdout: they may contain expanded secrets.
        raise RuntimeError("Docker Compose rejected the supplied configuration")
    try:
        return json.loads(proc.stdout)
    except (ValueError, TypeError):
        raise RuntimeError("Docker Compose did not return valid JSON") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--compose-file", default="docker-compose.yml", type=Path)
    args = parser.parse_args(argv)
    try:
        issues = verify(render_compose(
            env_file=args.env_file, compose_file=args.compose_file,
        ))
    except RuntimeError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 2
    if issues:
        for issue in issues:
            print(f"NO-GO: {issue}", file=sys.stderr)
        return 1
    print("PRIVATE PILOT PORT POLICY PASS: db/api/web loopback-only.")
    print("This does not attest host firewall, deployment safety or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
