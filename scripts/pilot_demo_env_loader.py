#!/usr/bin/env python3
"""Read a deliberately restricted synthetic Pilot .env without executing shell.

This loader is only for the MT ORION design-partner preflight, not a general
Docker Compose dotenv implementation. It emits NUL-delimited KEY=VALUE records
to stdout only after validating all entries and the pre-seed safety policy.
Redirect stdout into a temporary operator-private file, never CI logs.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

from pilot_demo_seed_guard import DemoSeedGuardError, check

NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
DANGEROUS = frozenset((
    "BASH_ENV", "ENV", "IFS", "PATH", "CDPATH", "HOME", "SHELLOPTS",
    "BASHOPTS", "GLOBIGNORE", "PS4", "PROMPT_COMMAND", "TMPDIR",
    "NODE_OPTIONS", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
))
DANGEROUS_PREFIXES = ("BASH_", "LD_", "PYTHON", "GIT_", "NPM_CONFIG_")
MAX_ENV_BYTES = 65536


class SyntheticEnvError(ValueError):
    """Sanitized parsing error: never copy untrusted lines or secret values."""


def parse_env(text: str) -> dict[str, str]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_ENV_BYTES:
        raise SyntheticEnvError("invalid or oversized synthetic environment")
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SyntheticEnvError("malformed synthetic environment assignment")
        name, value = line.split("=", 1)
        if (not NAME.fullmatch(name) or name in DANGEROUS
                or name.startswith(DANGEROUS_PREFIXES)
                or name in env):
            raise SyntheticEnvError("unsafe or duplicate synthetic environment key")
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1]:
                raise SyntheticEnvError("malformed synthetic environment quote")
            value = value[1:-1]
        elif any(c.isspace() for c in value):
            raise SyntheticEnvError("unquoted whitespace in synthetic environment")
        if (any(c in value for c in ("$", "`", "\\"))
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise SyntheticEnvError("unsupported synthetic environment interpolation")
        env[name] = value
    return env


def load(path: Path) -> dict[str, str]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ENV_BYTES:
            raise SyntheticEnvError("synthetic environment file is unsafe or unavailable")
        env = parse_env(path.read_text(encoding="utf-8"))
        check(env)
        if any("REPLACE_WITH_" in value for value in env.values()):
            raise SyntheticEnvError("synthetic environment contains placeholders")
        return env
    except (OSError, UnicodeError):
        raise SyntheticEnvError("synthetic environment unreadable") from None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("NO-GO: exactly one private synthetic env-file path required", file=sys.stderr)
        return 2
    try:
        values = load(Path(args[0]))
    except (SyntheticEnvError, DemoSeedGuardError) as exc:
        # Both exception types use fixed messages without copying private input.
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    # A NUL delimiter makes shell parsing non-evaluating and unambiguous.
    # stdout is secret-bearing: callers MUST NOT log or upload it.
    sys.stdout.buffer.write(b"".join(
        (key + "=" + value).encode("utf-8") + b"\0"
        for key, value in values.items()
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
