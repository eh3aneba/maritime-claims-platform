#!/usr/bin/env python3
"""Fail-closed, no-network guard before MT ORION demo seed/startup.

This validates operator-supplied configuration only. It cannot prove that a
Docker host or its existing volumes contain no customer data; the separate
fresh-host and operator review rules still apply.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit


class DemoSeedGuardError(ValueError):
    """Fixed error text without leaking passwords, hostnames or URLs."""


def check(env: dict[str, str]) -> None:
    if env.get("MCRI_SYNTHETIC_ONLY_CONFIRM") != "YES":
        raise DemoSeedGuardError("explicit synthetic-only operator confirmation missing")
    if env.get("APP_ENV") not in {"test", "pilot"}:
        raise DemoSeedGuardError("demo seed prohibited outside test/pilot")
    if env.get("AI_PROVIDER") != "disabled":
        raise DemoSeedGuardError("demo seed requires disabled external AI")
    if env.get("MALWARE_SCAN_ENABLED") != "true":
        raise DemoSeedGuardError("demo seed requires enabled malware scanning")
    if env.get("STORAGE_BACKEND") != "local":
        raise DemoSeedGuardError("demo seed requires isolated local evidence storage")
    try:
        database = urlsplit(env.get("DATABASE_URL", ""))
        expected_db = env.get("POSTGRES_DB", "")
        expected_user = env.get("POSTGRES_USER", "")
        database_safe = (
            database.scheme == "postgresql+psycopg"
            and database.hostname == "db"
            and database.port == 5432
            and bool(expected_db)
            and database.path == "/" + expected_db
            and bool(expected_user)
            and database.username == expected_user
            and bool(database.password)
            and not database.query
            and not database.fragment
        )
    except ValueError:
        database_safe = False
    if not database_safe:
        raise DemoSeedGuardError("demo seed database must be the internal Compose db")
    try:
        api = urlsplit(env.get("NEXT_PUBLIC_API_BASE_URL", ""))
        api_safe = (
            api.scheme == "http"
            and api.hostname in {"127.0.0.1", "localhost"}
            and api.port == 8000
            and api.path == "/api/v1"
            and not api.username
            and not api.password
            and not api.query
            and not api.fragment
        )
    except ValueError:
        api_safe = False
    if not api_safe:
        raise DemoSeedGuardError("demo seed API target must be local loopback")


def main() -> int:
    try:
        check(dict(os.environ))
    except DemoSeedGuardError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    print("SYNTHETIC DEMO CONFIG ACCEPTED — existing host data and release approval NOT verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
