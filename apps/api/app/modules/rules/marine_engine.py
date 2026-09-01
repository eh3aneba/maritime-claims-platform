from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from app.modules.rules.marine_extensions import (
    EXTENSION_RULES,
    MARINE_EXTENSION_VERSION,
    evaluate_extension_rules,
    extension_registry_hash,
)
from app.modules.rules.marine_registry import (
    MARINE_REGISTRY_VERSION as BASE_REGISTRY_VERSION,
    MARINE_RULES as BASE_RULES,
    MarineRuleEvaluation,
    MarineRuleStatus,
    evaluate_marine_rules as evaluate_base_rules,
    registry_hash as base_registry_hash,
)

MARINE_REGISTRY_VERSION = MARINE_EXTENSION_VERSION
REGISTRY_MANIFEST = {
    "registry_version": MARINE_REGISTRY_VERSION,
    "effective_from": "2026-09-01",
    "supersedes": BASE_REGISTRY_VERSION,
    "base_registry_version": BASE_REGISTRY_VERSION,
    "extension_registry_version": MARINE_EXTENSION_VERSION,
    "publication_model": "immutable versioned rule definitions; material changes require a new registry version",
}

MARINE_RULES = tuple(BASE_RULES) + tuple(EXTENSION_RULES)


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def registry_hash() -> str:
    return _hash({
        "manifest": REGISTRY_MANIFEST,
        "base_registry_hash": base_registry_hash(),
        "extension_registry_hash": extension_registry_hash(),
    })


def evaluate_marine_rules(
    *,
    claim: Any,
    fact_rows: Iterable[Any],
    documents: Iterable[Any],
    costs: Iterable[Any],
    policy: Any,
) -> tuple[MarineRuleEvaluation, ...]:
    fact_rows = tuple(fact_rows)
    documents = tuple(documents)
    costs = tuple(costs)
    base = evaluate_base_rules(
        claim=claim,
        fact_rows=fact_rows,
        documents=documents,
        costs=costs,
    )
    extensions = evaluate_extension_rules(
        claim=claim,
        fact_rows=fact_rows,
        documents=documents,
        costs=costs,
        policy=policy,
    )
    seen: set[str] = set()
    combined: list[MarineRuleEvaluation] = []
    for evaluation in (*base, *extensions):
        if evaluation.rule_id in seen:
            raise ValueError(f"Duplicate Marine Rule ID in composed registry: {evaluation.rule_id}")
        seen.add(evaluation.rule_id)
        combined.append(evaluation)
    return tuple(combined)


__all__ = [
    "MARINE_REGISTRY_VERSION",
    "MARINE_RULES",
    "MarineRuleEvaluation",
    "MarineRuleStatus",
    "REGISTRY_MANIFEST",
    "evaluate_marine_rules",
    "registry_hash",
]
