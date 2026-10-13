#!/usr/bin/env python3
"""Read a deliberately restricted synthetic Pilot .env without executing shell.

This loader is only for the MT ORION design-partner preflight, not a general
Docker Compose dotenv implementation. It emits NUL-delimited KEY=VALUE records
to stdout only after validating all entries and the pre-seed safety policy.
Redirect stdout into a temporary operator-private file, never CI logs.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import sys

from pilot_demo_seed_guard import DemoSeedGuardError, check

NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
DANGEROUS = frozenset((
    "BASH_ENV", "ENV", "IFS", "PATH", "CDPATH", "HOME", "SHELLOPTS",
    "BASHOPTS", "GLOBIGNORE", "PS4", "PROMPT_COMMAND", "TMPDIR",
    "NODE_OPTIONS", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
))
DANGEROUS_PREFIXES = ("BASH_", "LD_", "PYTHON", "GIT_", "NPM_CONFIG_", "DOCKER_", "COMPOSE_")
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
        if (any(c in value for c in ("$", "`", "\\", '"', "'"))
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
    if len(args) == 1:
        source, snapshot = Path(args[0]), None
    elif len(args) == 3 and args[1] == "--snapshot":
        source, snapshot = Path(args[0]), Path(args[2])
    else:
        print("NO-GO: one source and optional exclusive --snapshot path required",
              file=sys.stderr)
        return 2
    try:
        values = load(source)
        if snapshot is not None:
            # One parsed source, one immutable-for-this-run Compose snapshot.
            # Exclusive create + private mode: no overwrite or symlink target.
            fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for key, value in values.items():
                    # Parser rejects quotes, backslashes, dollars, controls.
                    # Double-quoting all values retains literal whitespace/#.
                    stream.write(f'{key}="{value}"\n')
    except (SyntheticEnvError, DemoSeedGuardError) as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive private Compose snapshot", file=sys.stderr)
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
