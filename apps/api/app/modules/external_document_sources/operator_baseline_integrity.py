from __future__ import annotations

from collections.abc import Sequence

from app.modules.external_document_sources.evidence_family_binding_models import (
    ExternalDocumentSourceEvidenceFamilyBinding,
)
from app.modules.external_document_sources.recurring_baseline_transition_models import (
    ExternalDocumentSourceRecurringBaselineTransition,
    ExternalDocumentSourceRecurringBaselineTransitionReceipt,
)
from app.modules.external_document_sources.recurring_baseline_transition_service import (
    _completion_hash as _baseline_completion_hash,
    _receipt_hash as _baseline_receipt_hash,
    _request_hash as _baseline_request_hash,
    _safety as _baseline_safety,
)


def baseline_transition_is_integrity_valid(
    *,
    binding: ExternalDocumentSourceEvidenceFamilyBinding,
    transition: ExternalDocumentSourceRecurringBaselineTransition,
    receipts: Sequence[ExternalDocumentSourceRecurringBaselineTransitionReceipt],
) -> bool:
    """Validate one already-bounded current transition without provider/storage I/O.

    The operator read model intentionally does not invoke the full Phase-AD
    verifier per family because that would re-query the entire upstream lineage
    and create an N+1 query pattern. Candidate transitions and receipts are
    selected in set-based queries; this function verifies their immutable
    transition/receipt hashes and exact binding snapshot in memory.
    """

    try:
        if (
            transition.status != "established"
            or transition.provider_kind != "sftp"
            or transition.binding_id != binding.id
            or transition.claim_id != binding.claim_id
            or transition.profile_id != binding.profile_id
            or transition.document_family_id != binding.document_family_id
            or transition.profile_hash != binding.profile_hash
            or transition.stable_source_item_hash != binding.stable_source_item_hash
            or transition.binding_completion_hash != binding.completion_hash
            or transition.current_version_number < 2
            or transition.request_hash != _baseline_request_hash(transition)
            or transition.completion_hash != _baseline_completion_hash(transition)
        ):
            return False

        for field, expected in _baseline_safety().items():
            if bool(getattr(transition, field)) != expected:
                return False

        if len(receipts) != 1:
            return False
        receipt = receipts[0]
        if (
            receipt.organization_id != transition.organization_id
            or receipt.transition_id != transition.id
            or receipt.sequence_number != 1
            or receipt.event_type != "established"
            or receipt.status_after != "established"
            or receipt.actor_id != transition.authorized_by_id
            or receipt.reason != transition.authorization_reason
            or receipt.scope_hash != transition.scope_hash
            or receipt.decision_hash != transition.completion_hash
            or receipt.prior_receipt_hash is not None
            or receipt.receipt_hash != _baseline_receipt_hash(receipt)
        ):
            return False
        for field, expected in _baseline_safety().items():
            if bool(getattr(receipt, field)) != expected:
                return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False
