"""Explicit-only local Ollama model inventory check for the H&M synthetic pilot.

GET /api/tags on literal IPv4 loopback. No source documents, user-supplied
model identifiers, persistence, remote endpoint, inference or raw logs.
An observed registry digest is NOT independent model attestation.
"""
from __future__ import annotations

import http.client
import json
import re
import sys
from typing import Any, Callable

from scripts.pilot_local_ai_synthetic_handoff import MODEL

_HOST = "127.0.0.1"
_PORT = 11434
_PATH = "/api/tags"
_MAX_RESPONSE_BYTES = 65536
_MAX_MODELS = 128
_DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")


class LocalModelInventoryError(RuntimeError):
    """Only code-owned failure class; never propagate model/HTTP body text."""


def _parse_local_tags(raw: bytes) -> dict[str, Any]:
    try:
        response = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        raise LocalModelInventoryError("malformed_registry_json") from None
    if type(response) is not dict or type(response.get("models")) is not list:
        raise LocalModelInventoryError("malformed_registry_structure")
    entries = response["models"]
    if len(entries) > _MAX_MODELS or not all(type(item) is dict for item in entries):
        raise LocalModelInventoryError("malformed_registry_structure")
    selected = [
        item for item in entries
        if item.get("name") == MODEL or item.get("model") == MODEL
    ]
    if not selected:
        return {
            "expected_model_tag": MODEL,
            "model_tag_observed": False,
            "observed_digest_sha256": None,
        }
    if len(selected) != 1:
        raise LocalModelInventoryError("ambiguous_model_registry")
    item = selected[0]
    if item.get("name") != MODEL or item.get("model") not in (None, MODEL):
        raise LocalModelInventoryError("ambiguous_model_registry")
    digest = item.get("digest")
    if type(digest) is not str:
        raise LocalModelInventoryError("invalid_registry_digest")
    match = _DIGEST.fullmatch(digest)
    if match is None:
        raise LocalModelInventoryError("invalid_registry_digest")
    return {
        "expected_model_tag": MODEL,
        "model_tag_observed": True,
        "observed_digest_sha256": match.group(1),
    }


def inspect_fixed_local_model_inventory(
    connection_factory: Callable[..., Any] = http.client.HTTPConnection,
) -> dict[str, Any]:
    """Read a bounded localhost model registry with no inference or writes."""
    conn = connection_factory(_HOST, _PORT, timeout=5)
    try:
        conn.request("GET", _PATH, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise LocalModelInventoryError("local_registry_unavailable")
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise LocalModelInventoryError("local_registry_response_too_large")
    except LocalModelInventoryError:
        raise
    except (OSError, TimeoutError, http.client.HTTPException):
        raise LocalModelInventoryError("local_registry_unavailable") from None
    finally:
        conn.close()

    observed = _parse_local_tags(raw)
    return {
        "scope": "synthetic_local_pc_inventory_only",
        "registry": "ollama_loopback_tag_listing",
        **observed,
        "observed_digest_source_attested": False,
        "model_artifact_independently_attested": False,
        "model_execution_verified": False,
        "network_egress_isolation_verified": False,
        "human_review_completed": False,
        "pilot_accepted": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--inspect-fixed-local-ollama-tag"]:
        print("local_model_inventory_explicit_opt_in_required")
        return 2
    try:
        summary = inspect_fixed_local_model_inventory()
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0 if summary["model_tag_observed"] else 1
    except Exception:
        # A fixed error string only: never echo HTTP/JSON, fixture or stack.
        print("local_model_inventory_inspection_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
