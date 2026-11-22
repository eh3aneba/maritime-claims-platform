"""Narrow admission predicates for first-manual synthetic recovery on hosted CI.

No operator dotenv, remote Docker daemon, customer path, cross-runner export
or real pilot recovery is authorized by these predicates.
"""
from __future__ import annotations

from pathlib import Path

from pilot_demo_seed_guard import DemoSeedGuardError, check
from pilot_demo_env_loader import SyntheticEnvError, load

ENV_FILE = ".env.first-manual-ci"
MARKER = "MCRI_CI_FIRST_MANUAL_RECOVERY"
DB = "mcri_performance"


def admitted(env: dict[str, str]) -> bool:
    if (
        env.get("APP_ENV") != "pilot"
        or env.get("GITHUB_ACTIONS") != "true"
        or env.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or env.get(MARKER) != "1"
        or env.get("POSTGRES_DB") != DB
        or env.get("POSTGRES_USER") != DB
        or env.get("NEXT_PUBLIC_API_BASE_URL") != "http://127.0.0.1:8000/api/v1"
        or env.get("MCRI_DEMO_ORG_SLUG") != "pilot"
        or env.get("MCRI_DEMO_EMAIL") != "manager@demo.mcri.app"
        or any(k in env for k in (
            "DOCKER_HOST", "DOCKER_CONTEXT", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME",
            "COMPOSE_PROJECT_DIRECTORY", "COMPOSE_PROFILES", "COMPOSE_REMOVE_ORPHANS",
        ))
        or env.get("COMPOSE_ENV_FILES", ENV_FILE) != ENV_FILE
    ):
        return False
    try:
        check(env)
    except DemoSeedGuardError:
        return False
    return True


def admitted_source(env_file: str, env: dict[str, str]) -> bool:
    if env_file != ENV_FILE or not admitted(env):
        return False
    try:
        values = load(Path(env_file))
    except (SyntheticEnvError, DemoSeedGuardError):
        return False
    # Bind all literal configuration fields to the same CI-generated file;
    # never print the values or accept an ambient override of one of them.
    return all(env.get(key) == value for key, value in values.items())
