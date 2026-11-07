"""Reject the explicitly unapproved Edge source in the production Dockerfile.

This bounded literal-source check is not package-signature verification,
complete Dockerfile analysis, vulnerability admission or a scanner exception.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote


def validate_sources(source: str) -> None:
    if "\x00" in source:
        raise ValueError("production_dockerfile_invalid")
    lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.lower().startswith("# escape=") and stripped[9:].strip() != "\\":
            raise ValueError("production_dockerfile_escape_unsupported")
        if not stripped.startswith("#"):
            lines.append(line)
    logical = re.sub(r"\\\n[ \t]*", "", "\n".join(lines))
    if not re.search(r"(?im)^\s*FROM\s+\S+", logical):
        raise ValueError("production_dockerfile_missing_from")
    if re.search(r"(?i)/alpine/edge(?=[/\s\"';?#]|$)", unquote(logical)):
        raise ValueError("production_alpine_edge_source_not_approved")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dockerfile", type=Path)
    args = parser.parse_args()
    try:
        source = args.dockerfile.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print("production_dockerfile_unreadable", file=sys.stderr)
        return 2
    try:
        validate_sources(source)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Production source-literal check passed; vulnerability admission is separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
