"""Bounded offline source-file SHA-256 cross-check for a private OCR study.

This tool verifies bytes of the *locally supplied files* against a claimed
manifest hash. It cannot authenticate a file's origin, reviewer independence,
unseen holdout status, permissions, transcript accuracy, or pilot GO.
Never echo paths, pseudonyms, source text or hash values in results/errors.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
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


def _safe_relative_file(
    root: Path, relative: Any,
) -> tuple[Path, tuple[int, int], tuple[tuple[int, int], ...]]:
    _require(type(relative) is str and 1 <= len(relative) <= 512)
    # Restrict to relative slash-separated paths with no implicit or parent
    # components; this also disallows backslash traversal on Windows.
    _require("\\" not in relative and "\x00" not in relative)
    _require(not relative.startswith("/") and ":" not in relative)
    pieces = relative.split("/")
    _require(all(piece not in ("", ".", "..") for piece in pieces))
    current = root
    root_info = root.lstat()
    _require(stat.S_ISDIR(root_info.st_mode))
    directories = [(root_info.st_dev, root_info.st_ino)]
    final_info: os.stat_result | None = None
    for index, piece in enumerate(pieces):
        current = current / piece
        info = current.lstat()
        _require(not stat.S_ISLNK(info.st_mode))
        if index < len(pieces) - 1:
            _require(stat.S_ISDIR(info.st_mode))
            directories.append((info.st_dev, info.st_ino))
        else:
            _require(stat.S_ISREG(info.st_mode))
            _require(0 < info.st_size <= _MAX_FILE_BYTES)
            final_info = info
    _require(current.resolve().is_relative_to(root.resolve()))
    _require(final_info is not None)
    # Carry the verified file identity across the gap between path inspection
    # and descriptor acquisition. O_NOFOLLOW alone only guards the last
    # component, not a swapped intermediate directory.
    return current, (final_info.st_dev, final_info.st_ino), tuple(directories)


def _verified_hash(
    file_path: Path, *, source_root: Path,
    expected_identity: tuple[int, int],
    expected_directories: tuple[tuple[int, int], ...],
) -> tuple[str, int]:
    # On supported POSIX hosts, descend from a checked source-root directory
    # descriptor and refuse symlinks at EVERY path component. Checking only
    # the last file inode cannot detect an intermediate directory swap to a
    # different tree containing a hard link to that same file.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    secure_walk = (
        os.name == "posix"
        and bool(getattr(os, "O_NOFOLLOW", 0))
        and bool(getattr(os, "O_DIRECTORY", 0))
    )
    with ExitStack() as opened:
        if secure_walk:
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            parts = file_path.relative_to(source_root).parts
            _require(len(parts) == len(expected_directories))
            parent_fd = os.open(source_root, directory_flags)
            opened.callback(os.close, parent_fd)
            root_stat = os.fstat(parent_fd)
            _require(
                (root_stat.st_dev, root_stat.st_ino) == expected_directories[0]
            )
            for piece, expected_dir in zip(
                parts[:-1], expected_directories[1:], strict=True
            ):
                parent_fd = os.open(piece, directory_flags, dir_fd=parent_fd)
                opened.callback(os.close, parent_fd)
                directory_info = os.fstat(parent_fd)
                _require(
                    (directory_info.st_dev, directory_info.st_ino) == expected_dir
                )
            fd = os.open(parts[-1], flags, dir_fd=parent_fd)
        else:
            # Windows does not support POSIX openat dir_fds. Preserve the
            # pre-existing no-symlink lstat + descriptor-identity checks;
            # do not claim race-free path custody on this platform.
            fd = os.open(file_path, flags)
        opened.callback(os.close, fd)
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= _MAX_FILE_BYTES)
        _require((before.st_dev, before.st_ino) == expected_identity)
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
        path, inspected_identity, inspected_dirs = _safe_relative_file(
            root, entry["relative_path"]
        )
        _require(path not in observed_paths)
        observed_paths.add(path)
        actual_hash, size = _verified_hash(
            path, source_root=root, expected_identity=inspected_identity,
            expected_directories=inspected_dirs,
        )
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
