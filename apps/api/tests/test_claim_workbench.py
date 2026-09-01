from datetime import UTC, date, datetime, timedelta

from app.core.security import hash_password
from app.modules.claims.models import Claim
from app.modules.organizations.models import Organization
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation, RecoveryTimebarSnapshot
from app.modules.severity_reserve.models import SeverityReserveEvaluation, SeverityReserveSnapshot
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD


def setup_function() -> None:
    reset_database()


def _login(slug: str, email: str) -> None:
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={
        "organization_slug": slug,
        "email": email,
        "password": TEST_PASSWORD,
    })
    assert response.status_code == 200, response.text


def _severity(db, org_id, claim_id, version: int, label: str, generated_at: datetime):
    snapshot = SeverityReserveSnapshot(
        organization_id=org_id,
        claim_id=claim_id,
        snapshot_version=version,
        engine_version="12D.1",
        source_state_hash=f"{version}" * 64,
        snapshot_hash=f"{version + 1}" * 64,
        summary={},
        generated_at=generated_at,
    )
    db.add(snapshot); db.flush()
    evaluation = SeverityReserveEvaluation(
        organization_id=org_id,
        claim_id=claim_id,
        snapshot_id=snapshot.id,
        evaluation_key="handling-severity",
        kind="severity",
        status="triggered",
        title="Claim handling severity",
        severity_label=label,
        severity_score={"low": 1, "medium": 4, "high": 7, "critical": 11}[label],
        currency=None,
        lower_amount=None,
        upper_amount=None,
        rationale="Synthetic deterministic workflow-priority rationale",
        candidate_implication="Synthetic handling priority",
        recommended_action="Review source-linked factors",
        factors=[],
        missing_prerequisites=[],
        source_refs=[],
        evaluation_hash=(label[0] * 64),
    )
    db.add(evaluation)
    return snapshot, evaluation


def _seed() -> dict[str, str]:
    now = datetime.now(UTC)
    today = now.date()
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Workbench", slug="alpha-workbench")
        beta = Organization(name="Beta Workbench", slug="beta-workbench")
        db.add_all([alpha, beta]); db.flush()
        alpha_manager = User(
            organization_id=alpha.id,
            email="alpha-workbench@example.com",
            full_name="Alpha Workbench Manager",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        beta_manager = User(
            organization_id=beta.id,
            email="beta-workbench@example.com",
            full_name="Beta Workbench Manager",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        alpha_vessel = Vessel(organization_id=alpha.id, name="MT ALPHA TRIAGE", imo_number="7000401")
        beta_vessel = Vessel(organization_id=beta.id, name="MT BETA TRIAGE", imo_number="7000402")
        db.add_all([alpha_manager, beta_manager, alpha_vessel, beta_vessel]); db.flush()
        alpha_a = Claim(
            organization_id=alpha.id, vessel_id=alpha_vessel.id, handler_id=alpha_manager.id,
            claim_reference="MCRI-HM-2026-WB-A", incident_date=date(2026, 7, 1), notification_date=date(2026, 7, 2),
            incident_description="PRIVATE SYNTHETIC INCIDENT DETAIL A", currency="USD",
        )
        alpha_b = Claim(
            organization_id=alpha.id, vessel_id=alpha_vessel.id, handler_id=alpha_manager.id,
            claim_reference="MCRI-HM-2026-WB-B", incident_date=date(2026, 7, 3), notification_date=date(2026, 7, 4),
            incident_description="PRIVATE SYNTHETIC INCIDENT DETAIL B", currency="USD",
        )
        beta_claim = Claim(
            organization_id=beta.id, vessel_id=beta_vessel.id, handler_id=beta_manager.id,
            claim_reference="MCRI-HM-2026-WB-BETA", incident_date=date(2026, 7, 5), notification_date=date(2026, 7, 6),
            incident_description="PRIVATE BETA INCIDENT DETAIL", currency="USD",
        )
        db.add_all([alpha_a, alpha_b, beta_claim]); db.flush()

        # Old snapshot is deliberately critical; latest snapshot is low and must win.
        _severity(db, alpha.id, alpha_a.id, 1, "critical", now - timedelta(days=2))
        _severity(db, alpha.id, alpha_a.id, 2, "low", now - timedelta(days=1))
        _severity(db, beta.id, beta_claim.id, 1, "critical", now)

        recovery_snapshot = RecoveryTimebarSnapshot(
            organization_id=alpha.id,
            claim_id=alpha_b.id,
            snapshot_version=1,
            engine_version="12C.1",
            evaluation_date=today,
            source_state_hash="a" * 64,
            snapshot_hash="b" * 64,
            summary={},
            generated_at=now,
        )
        db.add(recovery_snapshot); db.flush()
        recovery = RecoveryTimebarEvaluation(
            organization_id=alpha.id,
            claim_id=alpha_b.id,
            snapshot_id=recovery_snapshot.id,
            evaluation_key="synthetic-timebar",
            kind="timebar",
            status="triggered",
            title="Synthetic candidate time-bar",
            counterparty=None,
            candidate_basis="Synthetic basis",
            trigger_date=today,
            period_value=5,
            period_unit="days",
            candidate_deadline=today + timedelta(days=5),
            days_remaining=5,
            urgency="high",
            rationale="Synthetic candidate only",
            candidate_implication="Human legal review required",
            recommended_action="Review candidate deadline",
            missing_prerequisites=[],
            source_refs=[],
            evaluation_hash="c" * 64,
        )
        db.add(recovery); db.commit()
        return {"alpha_a": str(alpha_a.id), "alpha_b": str(alpha_b.id), "beta": str(beta_claim.id)}


def test_workbench_is_tenant_scoped_latest_snapshot_only_and_candidate_safe() -> None:
    ids = _seed()
    _login("alpha-workbench", "alpha-workbench@example.com")
    response = client.get("/api/v1/claim-workbench")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["operational_triage_only"] is True
    assert payload["claim_merits_decision"] is False
    assert payload["ranking_version"] == "12J.1"
    assert payload["metrics"]["claim_count"] == 2
    assert [row["claim_id"] for row in payload["rows"]] == [ids["alpha_b"], ids["alpha_a"]]

    first = payload["rows"][0]
    assert first["priority"] == "critical"
    assert first["nearest_due_semantics"] == "candidate_timebar"
    assert any(factor["category"] == "candidate_timebar" for factor in first["factors"])

    second = payload["rows"][1]
    severity = next(factor for factor in second["factors"] if factor["category"] == "handling_severity")
    assert severity["label"] == "Handling severity: low"
    assert second["rank_score"] < first["rank_score"]
    assert "PRIVATE SYNTHETIC INCIDENT DETAIL" not in response.text

    filtered = client.get("/api/v1/claim-workbench/queue?priority=critical&page=1&page_size=10")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["rows"][0]["claim_id"] == ids["alpha_b"]

    _login("beta-workbench", "beta-workbench@example.com")
    beta = client.get("/api/v1/claim-workbench")
    assert beta.status_code == 200
    assert beta.json()["metrics"]["claim_count"] == 1
    assert beta.json()["rows"][0]["claim_id"] == ids["beta"]
    assert ids["alpha_a"] not in beta.text and ids["alpha_b"] not in beta.text


def test_workbench_rank_hash_is_deterministic_for_unchanged_source_state() -> None:
    _seed()
    _login("alpha-workbench", "alpha-workbench@example.com")
    first = client.get("/api/v1/claim-workbench").json()["rows"]
    second = client.get("/api/v1/claim-workbench").json()["rows"]
    assert [(row["claim_id"], row["rank_hash"]) for row in first] == [
        (row["claim_id"], row["rank_hash"]) for row in second
    ]
