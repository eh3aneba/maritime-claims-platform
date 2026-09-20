from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.claims.models import Claim
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _establish_next_document_version,
    _lock_current_family_document,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
)
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel


pytestmark = pytest.mark.skipif(
    os.environ.get("EXTERNAL_EVIDENCE_VERSION_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "PostgreSQL external Evidence version concurrency regressions run only "
        "in the dedicated PostgreSQL CI job"
    ),
)


def _session_factory():
    engine = create_engine(
        os.environ["DATABASE_URL"],
        future=True,
        pool_pre_ping=True,
    )
    return engine, sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        class_=Session,
    )


def _seed_family() -> dict[str, UUID]:
    engine, SessionLocal = _session_factory()
    unique = uuid4().hex[:12]
    family_id = uuid4()
    try:
        with SessionLocal() as db:
            organization = Organization(
                name=f"Evidence Version Race {unique}",
                slug=f"evidence-version-race-{unique}",
            )
            db.add(organization)
            db.flush()

            admin = User(
                organization_id=organization.id,
                email=f"aa-race-{unique}@example.test",
                full_name="AA Concurrency Admin",
                password_hash="test-only-not-authenticated",
                role=UserRole.ADMIN,
                is_active=True,
            )
            vessel = Vessel(
                organization_id=organization.id,
                name=f"MT AA RACE {unique}",
                imo_number=None,
            )
            db.add_all([admin, vessel])
            db.flush()

            claim = Claim(
                organization_id=organization.id,
                vessel_id=vessel.id,
                claim_reference=f"AA-RACE-{unique}",
                incident_date=date(2026, 9, 1),
                notification_date=date(2026, 9, 2),
                incident_description=(
                    "PostgreSQL external Evidence family-version concurrency regression."
                ),
            )
            db.add(claim)
            db.flush()

            v1 = Document(
                id=uuid4(),
                organization_id=organization.id,
                claim_id=claim.id,
                uploaded_by_id=admin.id,
                document_family_id=family_id,
                version_number=1,
                is_current=True,
                filename="survey-v1.pdf",
                original_filename="survey-v1.pdf",
                document_type="External survey evidence",
                mime_type="application/pdf",
                file_size_bytes=101,
                file_hash="1" * 64,
                storage_key=f"test/{unique}/survey-v1.pdf",
                confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
                malware_scan_status=DocumentMalwareScanStatus.CLEAN,
                malware_scanned_at=datetime.now(UTC),
            )
            db.add(v1)
            db.commit()
            return {
                "organization_id": organization.id,
                "claim_id": claim.id,
                "admin_id": admin.id,
                "family_id": family_id,
                "v1_id": v1.id,
            }
    finally:
        engine.dispose()


def _current_documents(db: Session, ids: dict[str, UUID]) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(
                Document.organization_id == ids["organization_id"],
                Document.claim_id == ids["claim_id"],
                Document.document_family_id == ids["family_id"],
                Document.is_current.is_(True),
                Document.deleted_at.is_(None),
            )
        ).all()
    )


def test_concurrent_n_plus_one_transitions_allow_exactly_one_current_successor() -> None:
    ids = _seed_family()
    engine, SessionLocal = _session_factory()
    barrier = Barrier(2)

    def admit_one(label: str):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                prior = _lock_current_family_document(
                    db,
                    organization_id=ids["organization_id"],
                    claim_id=ids["claim_id"],
                    document_family_id=ids["family_id"],
                    expected_current_document_id=ids["v1_id"],
                )
                new = _establish_next_document_version(
                    db,
                    prior_document=prior,
                    executed_by_id=ids["admin_id"],
                    executed_at=datetime.now(UTC),
                    new_document_id=uuid4(),
                    original_filename=f"survey-v2-{label}.pdf",
                    mime_type="application/pdf",
                    file_size_bytes=200 + ord(label),
                    file_hash=(("a" if label == "A" else "b") * 64),
                    storage_key=f"test/aa-race/{uuid4().hex}.pdf",
                    malware_scanned_at=datetime.now(UTC),
                    replacement_reason=(
                        f"Concurrent later-version admission candidate {label}."
                    ),
                )
                db.commit()
                return ("ok", new.id)
            except ExternalDocumentSourceConflictError:
                db.rollback()
                return ("conflict", None)
            except IntegrityError:
                db.rollback()
                return ("conflict", None)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(admit_one, ("A", "B")))

        assert sorted(result[0] for result in results) == ["conflict", "ok"]

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(Document)
                    .where(
                        Document.organization_id == ids["organization_id"],
                        Document.claim_id == ids["claim_id"],
                        Document.document_family_id == ids["family_id"],
                        Document.deleted_at.is_(None),
                    )
                    .order_by(Document.version_number.asc())
                ).all()
            )
            assert len(rows) == 2
            assert [row.version_number for row in rows] == [1, 2]
            assert rows[0].is_current is False
            assert rows[1].is_current is True
            assert rows[1].supersedes_document_id == rows[0].id
            current = _current_documents(db, ids)
            assert len(current) == 1
            assert current[0].version_number == 2
    finally:
        engine.dispose()


def test_failed_next_version_insert_rolls_back_prior_supersession() -> None:
    ids = _seed_family()
    engine, SessionLocal = _session_factory()
    try:
        with SessionLocal() as db:
            prior = _lock_current_family_document(
                db,
                organization_id=ids["organization_id"],
                claim_id=ids["claim_id"],
                document_family_id=ids["family_id"],
                expected_current_document_id=ids["v1_id"],
            )
            with pytest.raises(IntegrityError):
                # Reusing the current file hash violates the claim-level unique
                # evidence hash after the prior row has been tentatively marked
                # non-current. The transaction rollback must restore v1.
                _establish_next_document_version(
                    db,
                    prior_document=prior,
                    executed_by_id=ids["admin_id"],
                    executed_at=datetime.now(UTC),
                    new_document_id=uuid4(),
                    original_filename="survey-v2-duplicate.pdf",
                    mime_type="application/pdf",
                    file_size_bytes=101,
                    file_hash="1" * 64,
                    storage_key=f"test/aa-rollback/{uuid4().hex}.pdf",
                    malware_scanned_at=datetime.now(UTC),
                    replacement_reason="Force a duplicate-hash rollback regression.",
                )
            db.rollback()

        with SessionLocal() as db:
            v1 = db.get(Document, ids["v1_id"])
            assert v1 is not None
            assert v1.is_current is True
            assert v1.superseded_at is None
            assert v1.superseded_by_id is None
            current = _current_documents(db, ids)
            assert len(current) == 1
            assert current[0].id == ids["v1_id"]
            total = list(
                db.scalars(
                    select(Document).where(
                        Document.organization_id == ids["organization_id"],
                        Document.claim_id == ids["claim_id"],
                        Document.document_family_id == ids["family_id"],
                    )
                ).all()
            )
            assert len(total) == 1
    finally:
        engine.dispose()
