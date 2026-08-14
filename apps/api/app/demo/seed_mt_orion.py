"""Seed a deterministic, fully populated MT ORION design-partner demo claim.

This is a synthetic demonstration utility. It does not call an external AI provider.
The resulting data is suitable for product walkthroughs only and must never be
represented as a real claim or real insurer data.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from starlette.datastructures import Headers

from app.core.security import hash_password
from app.db.session import create_session
from app.demo.mt_orion_fixture import AI_CASES, DOC_TYPES, MIME, FixtureProvider
from app.modules.assessments.service import approve_assessment, generate_assessment, get_assessment, review_section
from app.modules.chronology.service import build_chronology
from app.modules.claims.models import Claim, ClaimPriority, ClaimStatus, ClaimType
from app.modules.claims.schemas import ClaimCreate
from app.modules.claims.service import change_claim_status, create_claim, update_current_reserve
from app.modules.correspondence.models import ClaimCorrespondence
from app.modules.correspondence.schemas import CorrespondenceMarkSent
from app.modules.correspondence.service import mark_correspondence_sent, review_correspondence, submit_correspondence
from app.modules.documents.models import ConfidentialityLevel, DocumentProcessingStatus
from app.modules.documents.service import create_document_from_upload
from app.modules.financial.models import ReserveHistory
from app.modules.financial.service import build_financial_review
from app.modules.intelligence.models import AIReviewStatus, AIRun, DocumentExtraction
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.processing.service import process_job
from app.modules.review.service import review_extraction
from app.modules.rules.models import RequirementPriority, RequirementStatus
from app.modules.rules.service import evaluate_claim_rules, get_rule_summary
from app.modules.tasks.schemas import DocumentRequestCreate
from app.modules.tasks.service import create_document_request
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel

DEMO_EXTERNAL_REFERENCE = "MCRI-DEMO-MT-ORION"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Required demo environment variable is missing: {name}")
    return value


async def upload_fixture(db, claim: Claim, user: User, path: Path):
    with path.open("rb") as fh:
        upload = UploadFile(file=fh, filename=path.name, headers=Headers({"content-type": MIME[path.suffix]}))
        return await create_document_from_upload(
            db,
            claim=claim,
            current_user=user,
            upload=upload,
            document_type=DOC_TYPES[path.name],
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )


def process_text_jobs(db, document_ids: set, *, timeout_seconds: float = 60.0) -> None:
    """Process only demo text jobs without racing a concurrently running worker."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        jobs = list(
            db.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT,
                    DocumentProcessingJob.document_id.in_(document_ids),
                )
            )
        )
        if jobs and all(job.status == ProcessingJobStatus.COMPLETED for job in jobs):
            return
        failed = [job for job in jobs if job.status == ProcessingJobStatus.FAILED]
        if failed:
            raise RuntimeError(f"Demo text extraction failed for {len(failed)} document(s)")

        stmt = (
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT,
                DocumentProcessingJob.document_id.in_(document_ids),
                DocumentProcessingJob.status == ProcessingJobStatus.PENDING,
            )
            .order_by(DocumentProcessingJob.created_at.asc())
            .limit(1)
        )
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        job = db.scalar(stmt)
        if job is not None:
            job.status = ProcessingJobStatus.RUNNING
            job.locked_at = datetime.now(UTC)
            job.locked_by = "demo-seed"
            job.started_at = job.started_at or datetime.now(UTC)
            job.attempt_count += 1
            db.commit()
            process_job(db, job=job)
            db.expire_all()
            continue

        # A real worker may currently own the remaining jobs. Wait for it rather than
        # taking over RUNNING rows or duplicating extraction work.
        db.expire_all()
        time.sleep(0.25)

    raise RuntimeError("Timed out waiting for demo document text extraction")


def review_run(db, run: AIRun, reviewer: User) -> None:
    extractions = list(
        db.scalars(
            select(DocumentExtraction)
            .where(DocumentExtraction.ai_run_id == run.id)
            .order_by(DocumentExtraction.field_path)
        )
    )
    for extraction in extractions:
        if extraction.human_status != AIReviewStatus.PENDING:
            continue
        if extraction.field_path == "maintenance.interval_extension_approved":
            review_extraction(
                db,
                extraction=extraction,
                reviewer=reviewer,
                action="reject",
                reason=(
                    "Synthetic demo review: the source only states that no approved extension is on file; "
                    "it does not prove that no valid extension exists elsewhere."
                ),
            )
        else:
            review_extraction(
                db,
                extraction=extraction,
                reviewer=reviewer,
                action="approve",
                reason="Synthetic design-partner demo source reviewed.",
            )
    db.commit()


def main() -> None:
    fixture_dir = Path(os.getenv("MCRI_DEMO_FIXTURE_DIR", "/demo/mt-orion")).resolve()
    if not fixture_dir.is_dir():
        raise SystemExit(f"Demo fixture directory does not exist: {fixture_dir}")
    missing_files = [name for name in DOC_TYPES if not (fixture_dir / name).is_file()]
    if missing_files:
        raise SystemExit(f"Demo fixtures are incomplete: {', '.join(missing_files)}")

    org_slug = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot").strip().lower()
    org_name = os.getenv("MCRI_DEMO_ORG_NAME", "Pilot Marine Insurer").strip()
    email = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app").strip().lower()
    password = required_env("MCRI_DEMO_PASSWORD")
    if len(password) < 12:
        raise SystemExit("MCRI_DEMO_PASSWORD must contain at least 12 characters")

    with create_session() as db:
        existing_claim = db.scalar(
            select(Claim).where(
                Claim.external_reference == DEMO_EXTERNAL_REFERENCE,
                Claim.deleted_at.is_(None),
            )
        )
        if existing_claim is not None:
            print(
                f"MT ORION demo already exists: {existing_claim.claim_reference} "
                f"({existing_claim.id}). Seed is idempotent; no changes made."
            )
            return

        org = db.scalar(select(Organization).where(func.lower(Organization.slug) == org_slug))
        if org is None:
            org = Organization(name=org_name, slug=org_slug)
            db.add(org)
            db.flush()

        manager = db.scalar(
            select(User).where(User.organization_id == org.id, func.lower(User.email) == email)
        )
        if manager is None:
            manager = User(
                organization_id=org.id,
                email=email,
                full_name="Pilot Claims Manager",
                password_hash=hash_password(password),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            )
            db.add(manager)
            db.flush()
        else:
            manager.full_name = "Pilot Claims Manager"
            manager.password_hash = hash_password(password)
            manager.role = UserRole.CLAIMS_MANAGER
            manager.is_active = True
            db.flush()

        vessel = db.scalar(
            select(Vessel).where(
                Vessel.organization_id == org.id,
                Vessel.imo_number == "7000301",
                Vessel.deleted_at.is_(None),
            )
        )
        if vessel is None:
            vessel = Vessel(
                organization_id=org.id,
                name="MT ORION",
                imo_number="7000301",
                vessel_type="Oil Tanker",
                flag="Marshall Islands",
                class_society="Pilot Class",
            )
            db.add(vessel)
            db.flush()

        claim = create_claim(
            db,
            organization_id=org.id,
            current_user=manager,
            payload=ClaimCreate(
                vessel_id=vessel.id,
                incident_date=date(2026, 7, 10),
                notification_date=date(2026, 7, 11),
                incident_description=(
                    "Main engine turbocharger No.2 failure with abnormal vibration, load reduction "
                    "and subsequent shutdown. Synthetic design-partner demonstration claim."
                ),
                claim_type=ClaimType.HULL_MACHINERY,
                priority=ClaimPriority.HIGH,
                external_reference=DEMO_EXTERNAL_REFERENCE,
                estimated_loss=Decimal("550000"),
                currency="USD",
                handler_id=manager.id,
            ),
        )
        db.commit()

        change_claim_status(db, claim=claim, new_status=ClaimStatus.TRIAGE, current_user=manager)
        change_claim_status(db, claim=claim, new_status=ClaimStatus.INVESTIGATION, current_user=manager)
        db.commit()

        uploaded = {}
        for filename in DOC_TYPES:
            uploaded[filename] = asyncio.run(upload_fixture(db, claim, manager, fixture_dir / filename))
        document_ids = {doc.id for doc in uploaded.values()}
        process_text_jobs(db, document_ids)
        db.commit()
        if any(doc.processing_status != DocumentProcessingStatus.PROCESSED for doc in uploaded.values()):
            raise RuntimeError("One or more demo documents failed text extraction")

        for filename, (runner, payload_factory) in AI_CASES.items():
            run = runner(
                db,
                document=uploaded[filename],
                requested_by_id=manager.id,
                provider=FixtureProvider(payload_factory()),
            )
            review_run(db, run, manager)

        evaluate_claim_rules(db, claim=claim, user=manager, trigger="design_partner_demo_after_review")
        build_chronology(db, claim=claim, user=manager)
        db.commit()

        change_claim_status(db, claim=claim, new_status=ClaimStatus.FINANCIAL_REVIEW, current_user=manager)
        db.commit()
        evaluate_claim_rules(db, claim=claim, user=manager, trigger="design_partner_demo_financial")
        build_financial_review(db, claim=claim, user_id=manager.id)
        db.commit()

        update_current_reserve(db, claim=claim, amount=Decimal("575000"))
        db.add(
            ReserveHistory(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                amount=Decimal("575000"),
                currency="USD",
                reason="Synthetic demo reserve after review of alternative repair scopes.",
                created_by_id=manager.id,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

        evaluate_claim_rules(db, claim=claim, user=manager, trigger="design_partner_demo_before_request")
        summary = get_rule_summary(db, claim=claim)
        critical_missing = [
            requirement
            for requirement in summary.requirements
            if requirement.priority == RequirementPriority.CRITICAL
            and requirement.status == RequirementStatus.MISSING
        ]
        if critical_missing:
            batch, _ = create_document_request(
                db,
                claim=claim,
                user=manager,
                payload=DocumentRequestCreate(
                    all_critical=True,
                    due_date=date(2026, 7, 17),
                    recipient_label="Shipowner / Technical Manager",
                ),
            )
            correspondence = db.scalar(select(ClaimCorrespondence).where(ClaimCorrespondence.request_batch_id == batch.id))
            submit_correspondence(db, item=correspondence, user=manager)
            review_correspondence(
                db,
                item=correspondence,
                user=manager,
                approve=True,
                note="Synthetic pilot correspondence reviewed before recorded dispatch.",
            )
            mark_correspondence_sent(
                db,
                claim=claim,
                item=correspondence,
                user=manager,
                payload=CorrespondenceMarkSent(
                    confirm_sent=True,
                    channel="email",
                    external_reference="SYNTHETIC-DEMO-DISPATCH",
                ),
            )
            db.commit()

        assessment = generate_assessment(
            db,
            claim=claim,
            user=manager,
            allow_if_not_ready=True,
            override_reason=(
                "Synthetic design-partner demonstration assessment while policy and overhaul evidence "
                "remain outstanding."
            ),
        )
        assessment, sections = get_assessment(db, claim=claim, assessment_id=assessment.id)
        for section in sections:
            review_section(db, claim=claim, section=section, user=manager, action="approve", text=None)
        approve_assessment(
            db,
            claim=claim,
            assessment=assessment,
            user=manager,
            note="Synthetic design-partner demonstration assessment.",
        )
        db.commit()

        print("MT ORION design-partner demo seeded successfully.")
        print(f"Organization: {org.slug}")
        print(f"User: {manager.email}")
        print(f"Claim: {claim.claim_reference} ({claim.id})")
        print("Password: supplied through MCRI_DEMO_PASSWORD (not echoed).")
        print("This dataset is synthetic and for demonstration only.")


if __name__ == "__main__":
    main()
