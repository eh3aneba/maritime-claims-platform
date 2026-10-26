"""Bounded offline source-file SHA-256 cross-check for a private OCR study.

This tool verifies bytes of the *locally supplied files* against a claimed
manifest hash. It cannot authenticate a file's origin, reviewer independence,
unseen holdout status, permissions, transcript accuracy, or pilot GO.
Never echo paths, pseudonyms, source text or hash values in results/errors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from scripts.persian_ocr_blind_cohort_preflight import (
    _SOURCE_TYPES, _SCRIPT_TYPES, _SPLITS, _digest, _opaque_id, _strict_keys,
)
from scripts.persian_ocr_local_validation_metrics import (
    KINDS, _reject_duplicate_json_keys,
)

_MAX_JSON_BYTES = 2_000_000
_MAX_FILES = 2000
_MAX_FILE_BYTES = 256 * 1024 * 1024
_READ_CHUNK = 1024 * 1024


def _require(ok: bool) -> None:
    if not ok:
        raise ValueError("local_source_integrity_failed")


def _validate_manifest(manifest: Any) -> dict[str, tuple[str, str]]:
    _strict_keys(manifest, {
        "schema_version", "protocol_ref", "minimum_blind_holdout_sources",
        "predeclared_critical_kinds", "sources",
    })
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1)
    _opaque_id(manifest["protocol_ref"])
    _require(
        type(manifest["minimum_blind_holdout_sources"]) is int
        and 1 <= manifest["minimum_blind_holdout_sources"] <= _MAX_FILES
    )
    kinds = manifest["predeclared_critical_kinds"]
    _require(type(kinds) is list and 1 <= len(kinds) <= len(KINDS))
    _require(all(type(k) is str and k in KINDS for k in kinds))
    _require(len(kinds) == len(set(kinds)))
    sources = manifest["sources"]
    _require(type(sources) is list and 2 <= len(sources) <= _MAX_FILES)
    expected: dict[str, tuple[str, str]] = {}
    seen_hashes: set[str] = set()
    splits: set[str] = set()
    for source in sources:
        _strict_keys(source, {
            "case_ref", "source_file_sha256", "split", "source_kind",
            "script_mix", "expected_critical_kinds",
        })
        case = _opaque_id(source["case_ref"])
        digest = _digest(source["source_file_sha256"])
        split = source["split"]
        _require(type(split) is str and split in _SPLITS)
        _require(type(source["source_kind"]) is str and source["source_kind"] in _SOURCE_TYPES)
        _require(type(source["script_mix"]) is str and source["script_mix"] in _SCRIPT_TYPES)
        source_kinds = source["expected_critical_kinds"]
        _require(type(source_kinds) is list and 1 <= len(source_kinds) <= len(KINDS))
        _require(all(type(k) is str and k in KINDS for k in source_kinds))
        _require(len(source_kinds) == len(set(source_kinds)))
        _require(case not in expected and digest not in seen_hashes)
        seen_hashes.add(digest)
        splits.add(split)
        expected[case] = (digest, split)
    _require(splits == _SPLITS)
    return expected


def _safe_relative_file(root: Path, relative: Any) -> Path:
    _require(type(relative) is str and 1 <= len(relative) <= 512)
    # Restrict to relative slash-separated paths with no implicit or parent
    # components; this also disallows backslash traversal on Windows.
    _require("\\" not in relative and "\x00" not in relative)
    _require(not relative.startswith("/") and ":" not in relative)
    pieces = relative.split("/")
    _require(all(piece not in ("", ".", "..") for piece in pieces))
    current = root
    for index, piece in enumerate(pieces):
        current = current / piece
        info = current.lstat()
        _require(not stat.S_ISLNK(info.st_mode))
        if index < len(pieces) - 1:
            _require(stat.S_ISDIR(info.st_mode))
        else:
            _require(stat.S_ISREG(info.st_mode))
            _require(0 < info.st_size <= _MAX_FILE_BYTES)
    _require(current.resolve().is_relative_to(root.resolve()))
    return current


def _verified_hash(file_path: Path) -> tuple[str, int]:
    # Open with O_NOFOLLOW where available to reduce final-component
    # symlink swap races. Check descriptor identity before and after reads.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(file_path, flags)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= _MAX_FILE_BYTES)
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(os.dup(fd), "rb") as reader:
            while block := reader.read(_READ_CHUNK):
                total += len(block)
                _require(total <= _MAX_FILE_BYTES)
                digest.update(block)
        after = os.fstat(fd)
        _require(
            before.st_dev == after.st_dev
            and before.st_ino == after.st_ino
            and before.st_size == after.st_size == total
            and before.st_mtime_ns == after.st_mtime_ns
        )
        return digest.hexdigest(), total
    finally:
        os.close(fd)


def verify_source_bytes(
    manifest: Any, inventory: Any, *, root: Path,
) -> dict[str, Any]:
    """Verify all registered file bytes; no partial-success reporting."""
    expected = _validate_manifest(manifest)
    _strict_keys(inventory, {"schema_version", "files"})
    _require(type(inventory["schema_version"]) is int and inventory["schema_version"] == 1)
    entries = inventory["files"]
    _require(type(entries) is list and len(entries) == len(expected))
    _require(root.is_dir() and not root.is_symlink())
    root = root.resolve(strict=True)
    observed_cases: set[str] = set()
    observed_paths: set[Path] = set()
    total_bytes = 0
    for entry in entries:
        _strict_keys(entry, {"case_ref", "relative_path"})
        case = _opaque_id(entry["case_ref"])
        _require(case in expected and case not in observed_cases)
        observed_cases.add(case)
        path = _safe_relative_file(root, entry["relative_path"])
        _require(path not in observed_paths)
        observed_paths.add(path)
        actual_hash, size = _verified_hash(path)
        _require(actual_hash == expected[case][0])
        total_bytes += size
    _require(observed_cases == set(expected))
    return {
        "schema_version": 1,
        "measurement_kind": "local_source_file_byte_hash_comparison",
        "registered_source_files": len(expected),
        "locally_hash_matched_source_files": len(observed_cases),
        "development_source_files": sum(split == "development" for _, split in expected.values()),
        "holdout_source_files": sum(split == "blind_holdout" for _, split in expected.values()),
        "source_bytes_read_total": total_bytes,
        "local_source_hashes_matched": True,
        "source_provenance_independently_attested": False,
        "customer_permission_verified": False,
        "blinding_independently_attested": False,
        "reference_transcripts_independently_adjudicated": False,
        "negation_scope_semantics_verified": False,
        "human_bilingual_review_completed": False,
        "pilot_accepted": False,
        "warning": (
            "Local bytes matched self-supplied hashes only. File origin, "
            "authorization, image-to-reference fidelity, source independence "
            "and claims-pilot readiness are NOT established."
        ),
    }


def _read_json(path: Path) -> Any:
    _require(path.stat().st_size <= _MAX_JSON_BYTES)
    with path.open("r", encoding="utf-8") as src:
        return json.load(src, object_pairs_hook=_reject_duplicate_json_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private-local OCR source digest validation; no GO")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_source_bytes(
            _read_json(args.manifest), _read_json(args.inventory), root=args.source_root,
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("ocr_source_integrity_rejected", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
