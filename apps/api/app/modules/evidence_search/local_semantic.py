from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from typing import Iterable

LOCAL_SEMANTIC_PROVIDER = "local_in_process"
LOCAL_SEMANTIC_MODEL = "marine-concepts-hash-v1"
LOCAL_SEMANTIC_AUTHORIZATION_VERSION = "12E.2-local-private-v1"

# Deliberately small, reviewable marine-claims concept registry. This is not an
# external model and makes no network call. It exists only to bridge common
# equivalent terminology used in claim files while keeping retrieval private.
_CONCEPT_TERMS: dict[str, tuple[str, ...]] = {
    "turbocharger": ("turbocharger", "turbo", "tc"),
    "overhaul": ("overhaul", "overhauled", "overhauling", "service", "serviced", "servicing", "maintenance"),
    "running_hours": ("running hours", "operating hours", "service hours", "hours run", "running hour", "operating hour"),
    "failure_cause": ("cause", "causation", "root cause", "reason for failure", "failure reason", "failed due", "damage cause"),
    "vibration": ("vibration", "vibrating", "oscillation", "abnormal movement"),
    "repair_scope": ("repair scope", "scope of repair", "repair work", "permanent repair", "temporary repair", "replacement scope"),
    "maker": ("maker", "manufacturer", "oem", "original equipment manufacturer"),
    "workshop": ("workshop", "repairer", "repair yard", "service engineer", "service company"),
    "class": ("class", "classification society", "class surveyor", "class approval", "classification surveyor"),
    "policy": ("policy", "policy wording", "insurance wording", "insurance terms"),
    "notice": ("notice", "notification", "notify", "reported to insurers", "reporting requirement"),
    "deductible": ("deductible", "excess", "policy excess"),
    "time_bar": ("time bar", "time-bar", "limitation period", "deadline", "limitation deadline"),
    "charterparty": ("charterparty", "charter party", "charter-party", "cp wording"),
    "towage": ("towage", "tow", "towing", "tug assistance"),
    "sts": ("sts", "ship to ship", "ship-to-ship", "lightering"),
    "general_average": ("general average", "ga declaration", "average adjustment", "ga absorption"),
}

_TERM_TO_CONCEPT: dict[str, str] = {
    term: concept
    for concept, terms in _CONCEPT_TERMS.items()
    for term in terms
}


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def authorization_metadata() -> dict[str, object]:
    payload = {
        "provider": LOCAL_SEMANTIC_PROVIDER,
        "model": LOCAL_SEMANTIC_MODEL,
        "authorization_version": LOCAL_SEMANTIC_AUTHORIZATION_VERSION,
        "execution": "local_in_process",
        "network_egress": False,
        "external_provider": False,
        "restricted_evidence_allowed": True,
    }
    payload["authorization_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _phrase_concepts(normalized: str) -> Counter[str]:
    output: Counter[str] = Counter()
    for term, concept in _TERM_TO_CONCEPT.items():
        if " " in term and term in normalized:
            output[f"concept:{concept}"] += 2.0
    return output


def _features(value: str) -> Counter[str]:
    normalized = _normalize(value)
    features = _phrase_concepts(normalized)
    tokens = re.findall(r"\w+", normalized, flags=re.UNICODE)
    for token in tokens:
        concept = _TERM_TO_CONCEPT.get(token)
        if concept:
            features[f"concept:{concept}"] += 1.5
        # Retain a small lexical signal inside the local vector so hybrid
        # scoring remains stable even for terms outside the concept registry.
        if len(token) >= 3:
            features[f"token:{token}"] += 0.35
    return features


def semantic_score(query: str, text: str) -> float:
    query_features = _features(query)
    text_features = _features(text)
    if not query_features or not text_features:
        return 0.0
    shared = set(query_features) & set(text_features)
    if not shared:
        return 0.0
    dot = sum(query_features[key] * text_features[key] for key in shared)
    query_norm = math.sqrt(sum(value * value for value in query_features.values()))
    text_norm = math.sqrt(sum(value * value for value in text_features.values()))
    if query_norm <= 0 or text_norm <= 0:
        return 0.0
    return round(min(1.0, dot / (query_norm * text_norm)), 6)


def candidate_terms(query: str, *, limit: int = 40) -> list[str]:
    """Expand a query only with reviewed local concept equivalents.

    The returned terms are used solely to find candidate rows inside the same
    tenant/claim SQL scope before local scoring. Nothing is transmitted outside
    the process.
    """
    normalized = _normalize(query)
    selected: list[str] = []
    concepts: set[str] = set()
    for term, concept in _TERM_TO_CONCEPT.items():
        if term in normalized:
            concepts.add(concept)
    for concept in sorted(concepts):
        for term in _CONCEPT_TERMS[concept]:
            if term not in selected:
                selected.append(term)
                if len(selected) >= limit:
                    return selected
    return selected


def has_semantic_concept(value: str) -> bool:
    return any(key.startswith("concept:") for key in _features(value))
