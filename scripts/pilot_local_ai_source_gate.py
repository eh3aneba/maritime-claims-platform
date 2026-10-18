"""Strict, read-only *synthetic* local-AI source-quote candidate boundary.

Does not call Ollama, verify a model, inspect customer Evidence, assign
coverage/liability, store records, or promote any model output to claim facts.
It accepts literal excerpts only; attribution and meaning still need humans.
"""
from __future__ import annotations

import re


class LocalAISourceGateError(ValueError):
    """Bounded failure code: never include untrusted document/model text."""


SCHEMA = "seeclaims-local-ai-source-quotes-v1"
SOURCE_KINDS = frozenset({"event_notice", "reported_statement", "intake_status"})
SOURCE_ID = re.compile(r"S[1-9][0-9]{0,2}\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_SOURCES = 16
MAX_ITEMS = 32
MAX_SOURCE_CHARS = 16_384
MAX_QUOTE_CHARS = 1_000


def evaluate_synthetic_source_quotes(sources: object, candidate: object) -> dict:
    """Validate a proposed *review queue*, never return any free-text claims.

    Each accepted item is the *exact* source excerpt assigned the caller's
    existing record kind and version. No model-written 'interpretation',
    'allegation', causation or insurance decision field can pass this
    narrow gate. Neither the caller's source labels nor its model metadata
    are independently proven here; they must be established upstream.
    """
    if type(sources) is not dict or not 1 <= len(sources) <= MAX_SOURCES:
        raise LocalAISourceGateError("invalid_sources")
    if type(candidate) is not dict or set(candidate) != {
        "schema", "model_id", "model_digest", "prompt_version", "items"
    }:
        raise LocalAISourceGateError("invalid_candidate")
    if candidate["schema"] != SCHEMA:
        raise LocalAISourceGateError("invalid_schema")
    if (
        not isinstance(candidate["model_id"], str)
        or not MODEL_ID.fullmatch(candidate["model_id"])
        or not isinstance(candidate["model_digest"], str)
        or not SHA256.fullmatch(candidate["model_digest"])
        or not isinstance(candidate["prompt_version"], str)
        or not VERSION.fullmatch(candidate["prompt_version"])
    ):
        raise LocalAISourceGateError("invalid_model_metadata")
    items = candidate["items"]
    if type(items) is not list or not 1 <= len(items) <= MAX_ITEMS:
        raise LocalAISourceGateError("invalid_items")

    for source_id, record in sources.items():
        if (
            not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id)
            or type(record) is not dict
            or set(record) != {"kind", "version", "body"}
            or not isinstance(record["kind"], str)
            or record["kind"] not in SOURCE_KINDS
            or not isinstance(record["version"], str)
            or not VERSION.fullmatch(record["version"])
            or not isinstance(record["body"], str)
            or not 1 <= len(record["body"]) <= MAX_SOURCE_CHARS
        ):
            raise LocalAISourceGateError("invalid_sources")
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if type(item) is not dict or set(item) != {
            "kind", "source_id", "source_version", "verbatim_excerpt"
        }:
            raise LocalAISourceGateError("invalid_item_shape")
        source_id = item["source_id"]
        if not isinstance(source_id, str) or source_id not in sources:
            raise LocalAISourceGateError("unknown_source")
        source = sources[source_id]
        if (
            item["kind"] != source["kind"]
            or item["source_version"] != source["version"]
        ):
            raise LocalAISourceGateError("source_lineage_mismatch")
        excerpt = item["verbatim_excerpt"]
        if (
            not isinstance(excerpt, str)
            or not 1 <= len(excerpt) <= MAX_QUOTE_CHARS
            or excerpt not in source["body"]
        ):
            raise LocalAISourceGateError("unsupported_quote")
        identity = (source_id, source["version"], excerpt)
        if identity in seen:
            raise LocalAISourceGateError("duplicate_quote")
        seen.add(identity)

    return {
        "schema": SCHEMA,
        "quote_count": len(items),
        "human_review_required": True,
        "authoritative_fact_updates": False,
        "coverage_or_liability_decisions": False,
        "external_ai_invoked": False,
        "pilot_accepted": False,
    }
