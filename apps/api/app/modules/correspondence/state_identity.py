from __future__ import annotations

import hashlib
import json

from app.modules.correspondence.models import ClaimCorrespondence


def correspondence_state_fingerprint(item: ClaimCorrespondence) -> str:
    """Return the deterministic identity of material authored/linked correspondence state.

    Workflow status, review metadata and external-dispatch metadata are intentionally excluded.
    Dynamic document-requirement status is also excluded here; request-context evolution is a
    separate governed concern handled by the document-request workflow.
    """

    payload = {
        "direction": item.direction.value,
        "kind": item.kind.value,
        "sensitivity": item.sensitivity.value,
        "sender_label": item.sender_label or "",
        "recipient_label": item.recipient_label or "",
        "subject": item.subject.strip(),
        "body": item.body.strip(),
        "request_batch_id": str(item.request_batch_id) if item.request_batch_id else None,
        "requirement_ids": sorted(str(value) for value in (item.requirement_ids or [])),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def bind_initial_correspondence_state(item: ClaimCorrespondence) -> ClaimCorrespondence:
    """Bind a newly constructed row before its first database flush."""

    item.state_version = 1
    item.state_fingerprint = correspondence_state_fingerprint(item)
    return item
