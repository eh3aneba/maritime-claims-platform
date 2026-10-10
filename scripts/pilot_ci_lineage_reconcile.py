"""Fail-closed comparison of synthetic claim lineage on a restored DB clone.

Raw SQL results, UUIDs, audit event details, review text and Document paths
remain ephemeral in process memory. Only fixed group counts are exported.
Not intended for unapproved customer databases or a production restore.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

# Hardcoded existing PostgreSQL table identifiers: never interpolate users'
# content, uncontrolled table names, IDs, SQL or metadata into the query.
CLAIM_TABLES = (
    "documents",
    "initial_assessments",
    "assessment_sections",
    "claim_correspondence",
    "correspondence_review_decisions",
    "reserve_history",
)
ORG_TABLES = ("audit_logs",)
ALL_TABLES = CLAIM_TABLES + ORG_TABLES
REQUIRED_NONEMPTY = frozenset((
    "documents", "initial_assessments", "assessment_sections", "reserve_history",
))
MAX_BYTES_PER_TABLE = 4 * 1024 * 1024
MAX_ROWS_PER_TABLE = 10_000


class LineageError(ValueError):
    """Only static errors; never include raw source rows."""


def sql_for(table: str) -> str:
    if table not in ALL_TABLES:
        raise LineageError("unapproved synthetic lineage table")
    filter_sql = (
        "t.organization_id = "
        "(SELECT organization_id FROM claims WHERE external_reference = "
        "'MCRI-DEMO-MT-ORION' LIMIT 1)"
        if table in ORG_TABLES else
        "t.claim_id = "
        "(SELECT id FROM claims WHERE external_reference = "
        "'MCRI-DEMO-MT-ORION' LIMIT 1)"
    )
    return (
        "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id), "
        "'[]'::jsonb)::text FROM " + table + " t WHERE " + filter_sql + ";"
    )


def canonical_fingerprint(raw: str) -> tuple[int, str]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES_PER_TABLE:
        raise LineageError("synthetic lineage query unavailable or oversized")
    try:
        rows = json.loads(raw)
    except ValueError:
        raise LineageError("malformed synthetic lineage response") from None
    if not isinstance(rows, list) or len(rows) > MAX_ROWS_PER_TABLE or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str)
        for row in rows
    ):
        raise LineageError("invalid synthetic lineage row structure")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise LineageError("duplicate synthetic lineage record ID")
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return len(rows), hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect_lineage(db: str, query: Callable[[str, str], str]) -> dict[str, tuple[int, str]]:
    readings: dict[str, tuple[int, str]] = {}
    for table in ALL_TABLES:
        result = canonical_fingerprint(query(db, sql_for(table)))
        if table in REQUIRED_NONEMPTY and result[0] < 1:
            raise LineageError("required synthetic lineage family empty")
        readings[table] = result
    return readings


def reconcile(source: dict[str, tuple[int, str]],
              restored: dict[str, tuple[int, str]]) -> dict[str, int]:
    if set(source) != set(ALL_TABLES) or set(restored) != set(ALL_TABLES):
        raise LineageError("incomplete synthetic lineage families")
    for table in ALL_TABLES:
        if source[table] != restored[table]:
            raise LineageError("synthetic recovered claim lineage differs")
    return {
        "lineage_families_compared": len(ALL_TABLES),
        "lineage_rows_compared": sum(count for count, _ in source.values()),
    }
