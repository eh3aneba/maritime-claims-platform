#!/usr/bin/env python3
"""Transfer synthetic DB+Evidence recovery bytes between distinct ephemeral CI jobs.

Only runs with the explicit GitHub Actions test markers; never exports customer
data, DB credentials, cookies, private keys or operational production backups.
A GitHub artifact is a transport/retention mechanism, not a signed recovery
point or an independent operator release approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys

from pilot_ci_independent_postgres import IndependentRestoreError, restore_and_verify
from pilot_ci_lineage_reconcile import ALL_TABLES, REQUIRED_NONEMPTY, MAX_ROWS_PER_TABLE
from pilot_recovery_pair import RecoveryEvidenceError, check_record, observe

SHA = re.compile(r"[a-f0-9]{40}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
REVISION = re.compile(r"[0-9]{4}_[a-z0-9_]+\Z")
SCHEMA = "mcri-synthetic-cross-runner-transfer-v1"
BASENAMES = frozenset((
    "synthetic.dump", "synthetic.dump.sha256", "synthetic.dump.meta",
    "synthetic-evidence.tar", "pair.json", "source-lineage.json",
))
FIXED_TRANSFER = Path("synthetic-recovery-transfer")
FIXED_REPORT = Path("artifacts/cross-runner-restore.json")
MAX_DUMP = 128 * 1024 * 1024
MAX_EVIDENCE = 128 * 1024 * 1024


class CrossRunnerError(ValueError):
    """Always a fixed private-data-safe message."""


def guard(*, sha: str, env: dict[str, str], mode: str) -> None:
    if (not SHA.fullmatch(sha) or env.get("APP_ENV") != "test"
        or env.get("POSTGRES_DB") != "mcri_performance"
        or env.get("POSTGRES_USER") != "mcri_performance"
        or env.get("MCRI_CI_RESTORE_PROBE") != "1"
        or env.get("GITHUB_ACTIONS") != "true"
        or env.get("MCRI_CI_CROSS_RUNNER_" + mode.upper()) != "1"):
        raise CrossRunnerError("synthetic cross-runner CI-only guard failed")


def checked_lineage(value: object) -> dict[str, tuple[int, str]]:
    if not isinstance(value, dict) or set(value) != set(ALL_TABLES):
        raise CrossRunnerError("incomplete source lineage fingerprint families")
    valid: dict[str, tuple[int, str]] = {}
    for table in ALL_TABLES:
        pair = value[table]
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
            or type(pair[0]) is not int or not 0 <= pair[0] <= MAX_ROWS_PER_TABLE
            or not isinstance(pair[1], str) or not DIGEST.fullmatch(pair[1])
            or (table in REQUIRED_NONEMPTY and pair[0] == 0)):
            raise CrossRunnerError("invalid source lineage fingerprint")
        valid[table] = (pair[0], pair[1])
    return valid


def validate_record(record: object, sha: str) -> dict:
    if not isinstance(record, dict) or set(record) != {
        "schema", "release_sha", "synthetic_claim_count",
        "source_alembic_revision", "source_lineage",
    } or record["schema"] != SCHEMA or record["release_sha"] != sha:
        raise CrossRunnerError("synthetic transfer source record identity invalid")
    if record["synthetic_claim_count"] != "1":
        raise CrossRunnerError("synthetic source claim count is not one")
    if (not isinstance(record["source_alembic_revision"], str)
        or not REVISION.fullmatch(record["source_alembic_revision"])):
        raise CrossRunnerError("synthetic source Alembic revision malformed")
    checked_lineage(record["source_lineage"])
    return record


def pair_valid(root: Path, sha: str) -> None:
    try:
        if (root.is_symlink() or not root.is_dir()
            or {p.name for p in root.iterdir()} != BASENAMES
            or any(not p.is_file() or p.is_symlink() for p in root.iterdir())):
            raise CrossRunnerError("synthetic recovery transfer file set invalid")
        supplied = json.loads((root / "pair.json").read_text(encoding="utf-8"))
        if not isinstance(supplied, dict):
            raise CrossRunnerError("synthetic recovery pair manifest malformed")
        actual = observe(db_dump=root / "synthetic.dump",
                         evidence_archive=root / "synthetic-evidence.tar",
                         release_sha=sha,
                         quiescence_ref=supplied.get("operator_quiescence_record_ref", ""))
        check_record(supplied, actual, sha)
    except (RecoveryEvidenceError, OSError, UnicodeError, ValueError):
        raise CrossRunnerError("synthetic recovery pair binding mismatch") from None


def export_pair(*, root: Path, dump: Path, archive: Path, manifest: Path,
                sha: str, claim_count: str, revision: str,
                source_lineage: dict, env: dict[str, str]) -> None:
    guard(sha=sha, env=env, mode="export")
    if root != FIXED_TRANSFER or claim_count != "1":
        raise CrossRunnerError("cross-runner export destination or claim scope invalid")
    record = validate_record({
        "schema": SCHEMA,
        "release_sha": sha,
        "synthetic_claim_count": claim_count,
        "source_alembic_revision": revision,
        "source_lineage": source_lineage,
    }, sha)
    if (dump.name != "synthetic.dump" or archive.name != "synthetic-evidence.tar"
        or manifest.name != "pair.json"):
        raise CrossRunnerError("unexpected synthetic source artifact names")
    src = (dump, Path(str(dump) + ".sha256"),
           Path(str(dump) + ".meta"), archive, manifest)
    if (any(not x.is_file() or x.is_symlink() for x in src)
        or dump.stat().st_size > MAX_DUMP or archive.stat().st_size > MAX_EVIDENCE):
        raise CrossRunnerError("synthetic transfer missing or too large")
    # Input pair MUST already be integrity-verified by the original probe;
    # independently verify it again before making private transfer copies.
    try:
        supplied = json.loads(manifest.read_text(encoding="utf-8"))
        actual = observe(db_dump=dump, evidence_archive=archive,
                         release_sha=sha,
                         quiescence_ref=supplied["operator_quiescence_record_ref"])
        check_record(supplied, actual, sha)
    except (OSError, ValueError, KeyError, RecoveryEvidenceError):
        raise CrossRunnerError("synthetic source recovery pair unavailable") from None
    try:
        root.mkdir(mode=0o700, exist_ok=False)
    except OSError:
        # Never overwrite, re-use or delete an existing transfer directory.
        raise CrossRunnerError("exclusive synthetic transfer directory unavailable") from None
    try:
        for item in src:
            with item.open("rb") as stream, (root / item.name).open("xb") as target:
                shutil.copyfileobj(stream, target, length=1024 * 1024)
        with (root / "source-lineage.json").open("x", encoding="utf-8") as target:
            json.dump(record, target, indent=2, sort_keys=True)
            target.write("\n")
        pair_valid(root, sha)
    except Exception:
        shutil.rmtree(root)
        raise


def verify(*, root: Path, sha: str, env: dict[str, str]) -> dict:
    guard(sha=sha, env=env, mode="restore")
    if root != FIXED_TRANSFER:
        raise CrossRunnerError("cross-runner verification path invalid")
    pair_valid(root, sha)
    try:
        if (root / "source-lineage.json").stat().st_size > 4096:
            raise CrossRunnerError("cross-runner source fingerprint record oversized")
        record = validate_record(
            json.loads((root / "source-lineage.json").read_text(encoding="utf-8")),
            sha,
        )
        result = restore_and_verify(
            dump=root / "synthetic.dump",
            archive=root / "synthetic-evidence.tar",
            release_sha=sha,
            expected_claim_count=record["synthetic_claim_count"],
            expected_revision=record["source_alembic_revision"],
            source_lineage=checked_lineage(record["source_lineage"]),
            env=env,
        )
    except (OSError, ValueError, UnicodeError, IndependentRestoreError):
        raise CrossRunnerError("separate CI runner recovery verification failed") from None
    if (result.get("separate_postgres_engine_restored") is not True
        or result.get("isolated_container_network_disabled") is not True
        or result.get("separate_engine_lineage_families_matched") != len(ALL_TABLES)
        or result.get("separate_engine_documents_matched", 0) < 1
        or result.get("pilot_authorized") is not False):
        raise CrossRunnerError("separate CI runner result incomplete")
    return {
        "schema": "mcri-synthetic-cross-runner-recovery-result-v1",
        "release_sha": sha,
        "observed_at_utc": datetime.now(timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "github_actions_separate_job_restored": True,
        "separate_postgres_engine_network_disabled": True,
        "lineage_families_reconciled": len(ALL_TABLES),
        "documents_reconciled": result["separate_engine_documents_matched"],
        "independent_physical_host_verified": False,
        "customer_environment_restore_verified": False,
        "atomic_external_storage_snapshot_verified": False,
        "production_recovery_drill_verified": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output != FIXED_REPORT:
            raise CrossRunnerError("cross-runner report destination invalid")
        record = verify(root=args.input, sha=args.sha, env=dict(os.environ))
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(record, out, indent=2, sort_keys=True)
            out.write("\n")
    except CrossRunnerError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cross-runner report could not be published", file=sys.stderr)
        return 2
    print("SEPARATE EPHEMERAL CI JOB PostgreSQL/Evidence RESTORE PASS — not Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
