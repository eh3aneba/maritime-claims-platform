from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
import os
from threading import Barrier
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.modules.adjustments.models import AdjustmentStatement, AdjustmentStatus
from app.modules.claims.models import Claim
from app.modules.organizations.models import Organization
from app.modules.settlements.models import (
    PaymentAuthorization,
    PaymentStatus,
    SettlementProposal,
    SettlementStatus,
    SettlementType,
)
from app.modules.settlements.schemas import PaymentCreate
from app.modules.settlements.service import approve_payment, create_payment, submit_payment
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel


pytestmark = pytest.mark.skipif(
    os.environ.get("PAYMENT_SETTLEMENT_POSTGRES_TEST") != "1"
    or not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL payment concurrency regressions run only in the dedicated PostgreSQL CI job",
)


def _session_factory():
    engine = create_engine(os.environ["DATABASE_URL"], future=True, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, class_=Session)


def _seed_case(*, payment_statuses: list[PaymentStatus]) -> dict[str, UUID]:
    engine, SessionLocal = _session_factory()
    unique = uuid4().hex[:12]
    try:
        with SessionLocal() as db:
            organization = Organization(name=f"Payment Race {unique}", slug=f"payment-race-{unique}")
            db.add(organization)
            db.flush()

            handler = User(
                organization_id=organization.id,
                email=f"handler-{unique}@example.test",
                full_name="Concurrency Handler",
                password_hash="test-only-not-authenticated",
                role=UserRole.CLAIMS_HANDLER,
                is_active=True,
            )
            manager_one = User(
                organization_id=organization.id,
                email=f"manager-one-{unique}@example.test",
                full_name="Concurrency Manager One",
                password_hash="test-only-not-authenticated",
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            )
            manager_two = User(
                organization_id=organization.id,
                email=f"manager-two-{unique}@example.test",
                full_name="Concurrency Manager Two",
                password_hash="test-only-not-authenticated",
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            )
            vessel = Vessel(
                organization_id=organization.id,
                name=f"MT PAYMENT RACE {unique}",
                imo_number=None,
            )
            db.add_all([handler, manager_one, manager_two, vessel])
            db.flush()

            claim = Claim(
                organization_id=organization.id,
                vessel_id=vessel.id,
                handler_id=handler.id,
                claim_reference=f"PAY-RACE-{unique}",
                incident_date=date(2026, 9, 1),
                notification_date=date(2026, 9, 2),
                incident_description="PostgreSQL payment settlement-cap concurrency regression.",
                currency="USD",
            )
            db.add(claim)
            db.flush()

            adjustment = AdjustmentStatement(
                organization_id=organization.id,
                claim_id=claim.id,
                created_by_id=handler.id,
                reviewed_by_id=manager_one.id,
                version=1,
                title="Concurrency adjustment",
                currency="USD",
                status=AdjustmentStatus.APPROVED,
                deductible_amount=Decimal("0"),
                other_deduction_amount=Decimal("0"),
                gross_claimed=Decimal("1000.00"),
                gross_considered=Decimal("1000.00"),
                net_adjusted=Decimal("1000.00"),
                source_manifest=[],
                source_manifest_version=2,
                source_state_hash=("aa" * 32),
                review_note="Approved fixture.",
                content_hash=("bb" * 32),
                reviewed_at=datetime.now(UTC),
            )
            db.add(adjustment)
            db.flush()

            settlement = SettlementProposal(
                organization_id=organization.id,
                claim_id=claim.id,
                adjustment_statement_id=adjustment.id,
                created_by_id=handler.id,
                reviewed_by_id=manager_one.id,
                disposition_by_id=manager_one.id,
                version=1,
                title="Accepted concurrency settlement",
                settlement_type=SettlementType.FINAL,
                status=SettlementStatus.ACCEPTED,
                currency="USD",
                amount=Decimal("1000.00"),
                terms="Accepted settlement for PostgreSQL concurrency coverage.",
                release_required=True,
                without_prejudice=True,
                source_adjustment_hash=adjustment.content_hash,
                source_snapshot={"adjustment_statement_id": str(adjustment.id)},
                review_note="Approved.",
                disposition_note="Accepted externally.",
                content_hash=("cc" * 32),
                reviewed_at=datetime.now(UTC),
                disposition_at=datetime.now(UTC),
            )
            db.add(settlement)
            db.flush()

            payment_ids: list[UUID] = []
            for index, status in enumerate(payment_statuses, start=1):
                payment = PaymentAuthorization(
                    organization_id=organization.id,
                    claim_id=claim.id,
                    settlement_id=settlement.id,
                    created_by_id=handler.id,
                    sequence=index,
                    status=status,
                    payee="Orion Shipowning Ltd",
                    currency="USD",
                    amount=Decimal("700.00"),
                    purpose=f"Concurrency payment {index}.",
                    rejection_note="Fixture rejected state." if status == PaymentStatus.REJECTED else None,
                )
                db.add(payment)
                db.flush()
                payment_ids.append(payment.id)

            db.commit()
            return {
                "claim_id": claim.id,
                "settlement_id": settlement.id,
                "handler_id": handler.id,
                "manager_one_id": manager_one.id,
                "manager_two_id": manager_two.id,
                **{f"payment_{index}_id": payment_id for index, payment_id in enumerate(payment_ids, start=1)},
            }
    finally:
        engine.dispose()


def _active_total(db: Session, settlement_id: UUID) -> Decimal:
    active = {
        PaymentStatus.DRAFT,
        PaymentStatus.UNDER_REVIEW,
        PaymentStatus.FIRST_APPROVED,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.PAID_EXTERNALLY,
    }
    rows = db.scalars(
        select(PaymentAuthorization).where(
            PaymentAuthorization.settlement_id == settlement_id,
            PaymentAuthorization.status.in_(active),
        )
    ).all()
    return sum((row.amount for row in rows), Decimal("0"))


def test_concurrent_payment_creates_serialize_on_settlement_cap() -> None:
    ids = _seed_case(payment_statuses=[])
    engine, SessionLocal = _session_factory()
    barrier = Barrier(2)

    def create_one(label: str):
        with SessionLocal() as db:
            claim = db.get(Claim, ids["claim_id"])
            handler = db.get(User, ids["handler_id"])
            assert claim is not None and handler is not None
            barrier.wait(timeout=10)
            try:
                item = create_payment(
                    db,
                    claim,
                    handler,
                    PaymentCreate(
                        settlement_id=ids["settlement_id"],
                        payee="Orion Shipowning Ltd",
                        amount=Decimal("700.00"),
                        purpose=f"Concurrent create {label}.",
                    ),
                )
                return ("ok", item.id)
            except HTTPException as exc:
                db.rollback()
                return ("error", exc.status_code)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create_one, ("A", "B")))

        assert sorted(result[0] for result in results) == ["error", "ok"]
        assert [result[1] for result in results if result[0] == "error"] == [422]

        with SessionLocal() as db:
            payments = db.scalars(
                select(PaymentAuthorization).where(
                    PaymentAuthorization.settlement_id == ids["settlement_id"]
                )
            ).all()
            assert len(payments) == 1
            assert _active_total(db, ids["settlement_id"]) == Decimal("700.00")
    finally:
        engine.dispose()


def test_concurrent_rejected_resubmits_allow_only_one_to_reenter_capacity() -> None:
    ids = _seed_case(payment_statuses=[PaymentStatus.REJECTED, PaymentStatus.REJECTED])
    engine, SessionLocal = _session_factory()
    barrier = Barrier(2)

    def resubmit(payment_key: str):
        with SessionLocal() as db:
            payment = db.get(PaymentAuthorization, ids[payment_key])
            handler = db.get(User, ids["handler_id"])
            assert payment is not None and handler is not None
            barrier.wait(timeout=10)
            try:
                item = submit_payment(db, payment, handler)
                return ("ok", item.id)
            except HTTPException as exc:
                db.rollback()
                return ("error", exc.status_code)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(resubmit, "payment_1_id"),
                pool.submit(resubmit, "payment_2_id"),
            ]
            results = [future.result(timeout=20) for future in futures]

        assert sorted(result[0] for result in results) == ["error", "ok"]
        assert [result[1] for result in results if result[0] == "error"] == [422]

        with SessionLocal() as db:
            rows = db.scalars(
                select(PaymentAuthorization).where(
                    PaymentAuthorization.settlement_id == ids["settlement_id"]
                )
            ).all()
            assert sorted(row.status.value for row in rows) == [
                PaymentStatus.REJECTED.value,
                PaymentStatus.UNDER_REVIEW.value,
            ]
            assert _active_total(db, ids["settlement_id"]) == Decimal("700.00")
    finally:
        engine.dispose()


def test_concurrent_distinct_manager_approvals_refresh_stale_payment_state() -> None:
    ids = _seed_case(payment_statuses=[PaymentStatus.UNDER_REVIEW])
    engine, SessionLocal = _session_factory()
    barrier = Barrier(2)

    def approve(manager_key: str, note: str):
        with SessionLocal() as db:
            # Deliberately load the same under-review row in both transactions
            # before either is allowed to enter approve_payment.
            payment = db.get(PaymentAuthorization, ids["payment_1_id"])
            manager = db.get(User, ids[manager_key])
            assert payment is not None and manager is not None
            assert payment.status == PaymentStatus.UNDER_REVIEW
            barrier.wait(timeout=10)
            item = approve_payment(db, payment, manager, note)
            return item.status

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(approve, "manager_one_id", "Concurrent approval one."),
                pool.submit(approve, "manager_two_id", "Concurrent approval two."),
            ]
            results = [future.result(timeout=20) for future in futures]

        assert set(results) == {PaymentStatus.FIRST_APPROVED, PaymentStatus.AUTHORIZED}

        with SessionLocal() as db:
            payment = db.get(PaymentAuthorization, ids["payment_1_id"])
            assert payment is not None
            assert payment.status == PaymentStatus.AUTHORIZED
            assert payment.first_approved_by_id in {ids["manager_one_id"], ids["manager_two_id"]}
            assert payment.second_approved_by_id in {ids["manager_one_id"], ids["manager_two_id"]}
            assert payment.first_approved_by_id != payment.second_approved_by_id
            assert payment.content_hash is not None
            assert _active_total(db, ids["settlement_id"]) == Decimal("700.00")
    finally:
        engine.dispose()


def test_concurrent_same_manager_cannot_supply_both_approvals() -> None:
    ids = _seed_case(payment_statuses=[PaymentStatus.UNDER_REVIEW])
    engine, SessionLocal = _session_factory()
    barrier = Barrier(2)

    def approve_same_manager(label: str):
        with SessionLocal() as db:
            payment = db.get(PaymentAuthorization, ids["payment_1_id"])
            manager = db.get(User, ids["manager_one_id"])
            assert payment is not None and manager is not None
            assert payment.status == PaymentStatus.UNDER_REVIEW
            barrier.wait(timeout=10)
            try:
                item = approve_payment(db, payment, manager, f"Same-manager race {label}.")
                return ("ok", item.status)
            except HTTPException as exc:
                db.rollback()
                return ("error", exc.status_code)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve_same_manager, ("A", "B")))

        assert sorted(result[0] for result in results) == ["error", "ok"]
        assert [result[1] for result in results if result[0] == "error"] == [409]

        with SessionLocal() as db:
            payment = db.get(PaymentAuthorization, ids["payment_1_id"])
            assert payment is not None
            assert payment.status == PaymentStatus.FIRST_APPROVED
            assert payment.first_approved_by_id == ids["manager_one_id"]
            assert payment.second_approved_by_id is None
            assert payment.content_hash is None
    finally:
        engine.dispose()
