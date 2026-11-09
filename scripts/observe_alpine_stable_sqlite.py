"""Read-only supported-stable Alpine SQLite candidate observation.

A changed package version is NOT a CVE fix, signature validation, successful
image build, or an authorized dependency decision. Never modifies production.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import sys
import tarfile
from urllib.request import Request, urlopen

BASELINE_VERSION = "3.53.4-r0"  # Last vulnerable version confirmed by hosted Grype.
ALPINE_RELEASE = "v3.24"  # Exactly the production Python base's supported branch.
ARCHITECTURES = ("x86_64", "aarch64")
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_INDEX_BYTES = 5 * 1024 * 1024
VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){2,3}-r[0-9]+\Z")


class ObservationError(RuntimeError):
    pass


def extract_sqlite_lib_version(index_bytes: bytes) -> str:
    """Read one exact P:sqlite-libs/V:VERSION record; ambiguity fails closed."""
    try:
        contents = index_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ObservationError("Invalid APKINDEX UTF-8") from exc
    versions: list[str] = []
    for record in contents.split("\n\n"):
        fields: dict[str, str] = {}
        for line in record.splitlines():
            if not line or len(line) < 3 or line[1] != ":":
                continue
            if line[0] in {"P", "V"}:
                if line[0] in fields:
                    raise ObservationError("Duplicate package name/version field")
                fields[line[0]] = line[2:]
        if fields.get("P") == "sqlite-libs":
            version = fields.get("V")
            if version is None or not VERSION_PATTERN.fullmatch(version):
                raise ObservationError("Malformed sqlite-libs version")
            versions.append(version)
    if len(versions) != 1:
        raise ObservationError(f"Expected exactly one sqlite-libs record, found {len(versions)}")
    return versions[0]


def sqlite_version_from_archive(archive_bytes: bytes) -> str:
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ObservationError("Oversize APKINDEX archive")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            members = [m for m in archive.getmembers() if m.name == "APKINDEX" and m.isfile()]
            if len(members) != 1 or members[0].size > MAX_INDEX_BYTES:
                raise ObservationError("Missing, duplicate or oversized APKINDEX")
            source = archive.extractfile(members[0])
            if source is None:
                raise ObservationError("APKINDEX unavailable")
            index = source.read(MAX_INDEX_BYTES + 1)
            if len(index) > MAX_INDEX_BYTES:
                raise ObservationError("Oversize APKINDEX")
            return extract_sqlite_lib_version(index)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ObservationError("Corrupt APKINDEX archive") from exc


def read_official_stable_version(architecture: str) -> tuple[str, str]:
    if architecture not in ARCHITECTURES:
        raise ObservationError("Unapproved APK architecture")
    url = (
        f"https://dl-cdn.alpinelinux.org/alpine/{ALPINE_RELEASE}/"
        f"main/{architecture}/APKINDEX.tar.gz"
    )
    # HTTPS default certificate verification; read-only, no APK installation.
    try:
        with urlopen(Request(url, headers={"User-Agent": "SeeClaims-stable-sqlite-read-only/1"}), timeout=20) as response:
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ObservationError("Official stable index unavailable") from exc
    return url, sqlite_version_from_archive(data)


def report_summary(results: list[tuple[str, str, str]]) -> tuple[str, bool]:
    if len(results) != len(ARCHITECTURES) or {a for a, _, _ in results} != set(ARCHITECTURES):
        raise ObservationError("Incomplete architecture observations")
    for arch, url, version in results:
        if arch not in ARCHITECTURES or not url.startswith(
            f"https://dl-cdn.alpinelinux.org/alpine/{ALPINE_RELEASE}/main/{arch}/"
        ) or not VERSION_PATTERN.fullmatch(version):
            raise ObservationError("Untrusted observation data")
    changed = any(version != BASELINE_VERSION for _, _, version in results)
    lines = [
        "### Supported Alpine stable SQLite package observation (read-only)",
        "",
        f"Pinned production branch: `{ALPINE_RELEASE}`; known affected baseline: `{BASELINE_VERSION}`.",
        "",
        "| Architecture | Observed sqlite-libs package | Official index |",
        "| --- | --- | --- |",
    ]
    for arch, url, version in results:
        lines.append(f"| `{arch}` | `{version}` | {url} |")
    lines += [
        "",
        (
            "**Candidate package change detected — HUMAN SECURITY REVIEW REQUIRED.** "
            "This is not a fix, scan result, provenance validation, or deployment approval."
            if changed else
            "**No package version change observed.** Existing four High CVEs remain a security hold."
        ),
        "The mandatory API, Worker, Web Grype image scans, all eleven required checks, "
        "approved source provenance and independent review remain binding.",
        "No Alpine Edge, local APK injection, scanner exception, or production change was performed.",
        "",
    ]
    return "\n".join(lines), changed


def main() -> int:
    results = []
    try:
        for architecture in ARCHITECTURES:
            url, version = read_official_stable_version(architecture)
            results.append((architecture, url, version))
        summary, changed = report_summary(results)
    except ObservationError as exc:
        print(f"ERROR: stable SQLite observation inconclusive: {exc}", file=sys.stderr)
        return 2
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as out:
            out.write(summary)
    print(summary)
    if changed:
        print("::notice title=Supported Alpine SQLite candidate::Package version changed; human review required; no CVE or image gate cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
