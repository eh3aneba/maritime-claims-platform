"""Read-only SQLite runtime evidence for final SeeClaims API and Worker images.

Runs with synthetic in-memory data, no network and no package installation.
This is NOT a vulnerability scan, a VEX ruling, or a CVE exception.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

PACKAGE_PATTERN = re.compile(r"sqlite-libs-(\d+(?:\.\d+){2,3}-r\d+)\Z")
ROLES = frozenset({"api", "worker"})


def extract_package_version(output: str) -> str:
    # With no package argument, apk info -v emits one name-version per
    # installed package. Passing a package name instead produces detailed,
    # multi-line metadata, not an unambiguous version inventory.
    lines = [line.strip() for line in output.splitlines()
             if line.strip().startswith("sqlite-libs-")]
    if len(lines) != 1:
        raise RuntimeError("Expected exactly one installed sqlite-libs version")
    match = PACKAGE_PATTERN.fullmatch(lines[0])
    if not match:
        raise RuntimeError("Unexpected installed SQLite package identifier")
    return match.group(1)


def sqlite_library_paths(maps: str) -> list[str]:
    paths = set()
    for line in maps.splitlines():
        fields = line.split()
        if len(fields) >= 6 and "/libsqlite3.so" in fields[-1]:
            paths.add(fields[-1])
    if not paths:
        raise RuntimeError("SQLite shared-library mapping could not be attested")
    return sorted(paths)


def get_evidence(role: str) -> dict:
    if role not in ROLES:
        raise RuntimeError("Unknown SeeClaims production image role")
    package = subprocess.run(
        ["/sbin/apk", "info", "-v"],
        check=True, capture_output=True, text=True, timeout=15,
    ).stdout
    version = extract_package_version(package)
    connection = sqlite3.connect(":memory:")
    try:
        flags = {row[0] for row in connection.execute("PRAGMA compile_options")}
        try:
            connection.execute("CREATE VIRTUAL TABLE synthetic_probe USING fts5(sample)")
        except sqlite3.OperationalError:
            fts5_available = False
        else:
            fts5_available = True
    finally:
        connection.close()
    return {
        "role": role,
        "sqlite_package_version": version,
        "python_sqlite_version": sqlite3.sqlite_version,
        "fts5_compile_option": "ENABLE_FTS5" in flags,
        "fts5_available_synthetic": fts5_available,
        "session_compile_option": "ENABLE_SESSION" in flags,
        "sqlite_cli_present": shutil.which("sqlite3") is not None,
        "mapped_sqlite_libraries": sqlite_library_paths(
            Path("/proc/self/maps").read_text(encoding="utf-8")
        ),
        "cve_clearance": False,
    }


def main() -> int:
    data = get_evidence(os.environ.get("SEECLAIMS_RUNTIME_ROLE", ""))
    print(json.dumps(data, sort_keys=True))
    print("RUNTIME EVIDENCE ONLY: four High CVEs remain subject to mandatory Grype scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
