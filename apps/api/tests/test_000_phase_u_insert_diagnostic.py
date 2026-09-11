import os
from pathlib import Path
from uuid import UUID

from app.modules.audit.service import write_audit_log
from app.modules.documents.recovery_read_ownership_transition_authorization_router import _audit_values
from app.modules.documents.recovery_read_ownership_transition_authorization_service import (
    request_read_ownership_transition_authorization,
)
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_evidence_recovery_read_ownership_transition_authorization import (
    REQUEST_REASON,
    _qualified_t,
)
from tests.test_evidence_recovery_restore_rehearsal import _fake_s3


def setup_function() -> None:
    reset_database()


def _emit(message: str) -> None:
    os.write(2, (message + "\n").encode("utf-8", errors="replace"))


def test_phase_u_insert_diagnostic(monkeypatch, tmp_path: Path) -> None:
    try:
        with _fake_s3() as endpoint:
            data = _qualified_t(monkeypatch, tmp_path, endpoint, slug="phase-u-diagnostic")
            with TestingSessionLocal() as db:
                requester = (
                    db.query(User)
                    .filter(
                        User.organization_id == UUID(str(data["org_id"])),
                        User.role == UserRole.ADMIN,
                    )
                    .order_by(User.created_at.asc())
                    .first()
                )
                assert requester is not None
                authorization, receipt, outcome = request_read_ownership_transition_authorization(
                    db,
                    organization_id=UUID(str(data["org_id"])),
                    claim_id=UUID(str(data["claim_id"])),
                    document_id=UUID(str(data["document_id"])),
                    phase_t_health_qualification_id=UUID(str(data["phase_t_health_qualification_id"])),
                    requested_by_id=requester.id,
                    reason=REQUEST_REASON,
                )
                assert outcome == "pending_second_approval"
                write_audit_log(
                    db,
                    organization_id=authorization.organization_id,
                    user_id=requester.id,
                    action="EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_REQUESTED",
                    entity_type="evidence_recovery_read_ownership_transition_authorization",
                    entity_id=authorization.id,
                    new_values={
                        **_audit_values(authorization),
                        "receipt_hash": receipt.receipt_hash if receipt else None,
                        "outcome": outcome,
                    },
                )
                db.commit()
    except BaseException as exc:
        _emit(f"PHASE_U_DIAGNOSTIC_EXCEPTION={exc!r}")
        os._exit(86)
    _emit("PHASE_U_DIAGNOSTIC_SEQUENCE_SUCCEEDED")
    os._exit(87)
