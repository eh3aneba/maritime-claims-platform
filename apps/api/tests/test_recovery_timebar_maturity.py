from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.documents.models import Document, DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.recovery_timebar.models import RecoveryCounterparty, TimebarScenario, TimebarScenarioReview
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _scenario_payload(**overrides) -> dict:
    payload = {
        "title": "Workshop contractual limitation alternative",
        "legal_basis": "Handler-entered contractual clause basis; legal effect requires review.",
        "source_reference": "Workshop Contract clause 12 supplied in claim file",
        "anchor_date": "2026-07-10",
        "period_value": 6,
        "period_unit": "months",
        "extension_value": None,
        "extension_unit": None,
        "extension_basis": None,
        "assumptions": "Assumes the handler-selected event is the contractual anchor and no contrary suspension applies.",
    }
    payload.update(overrides)
    return payload


def _create_scenario(claim_id: str, **overrides) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios",
        json=_scenario_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_current_document(claim_id: str, organization_id: UUID, user_id: UUID) -> Document:
    with TestingSessionLocal() as db:
        document = Document(
            organization_id=organization_id,
            claim_id=UUID(claim_id),
            uploaded_by_id=user_id,
            filename="workshop-contract.pdf",
            original_filename="workshop-contract.pdf",
            document_type="contract",
            mime_type="application/pdf",
            file_size_bytes=1200,
            file_hash="a" * 64,
            storage_key=f"tests/{claim_id}/workshop-contract-v1.pdf",
            document_family_id=uuid4(),
            version_number=1,
            is_current=True,
            processing_status=DocumentProcessingStatus.PROCESSED,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        db.expunge(document)
        return document


def _supersede_document(document: Document, *, user_id: UUID) -> Document:
    with TestingSessionLocal() as db:
        old = db.get(Document, document.id)
        assert old is not None
        old.is_current = False
        replacement = Document(
            organization_id=old.organization_id,
            claim_id=old.claim_id,
            uploaded_by_id=user_id,
            supersedes_document_id=old.id,
            filename="workshop-contract-v2.pdf",
            original_filename="workshop-contract-v2.pdf",
            document_type=old.document_type,
            mime_type=old.mime_type,
            file_size_bytes=1300,
            file_hash="b" * 64,
            storage_key=f"tests/{old.claim_id}/workshop-contract-v2.pdf",
            document_family_id=old.document_family_id,
            version_number=2,
            is_current=True,
            processing_status=DocumentProcessingStatus.PROCESSED,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
        )
        db.add(replacement)
        db.commit()
        db.refresh(replacement)
        db.expunge(replacement)
        return replacement


def test_multiple_human_scenarios_remain_alternatives_and_only_compute_calendar_candidates() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    first = _create_scenario(claim_id)
    second = _create_scenario(
        claim_id,
        title="Alternative two-year statutory hypothesis",
        legal_basis="Separately entered statutory hypothesis requiring legal verification.",
        source_reference="Handler legal research note LR-2026-04",
        period_value=2,
        period_unit="years",
        assumptions="Assumes, without deciding, that the selected statutory hypothesis and anchor date apply.",
    )

    assert first["candidate_deadline"] == "2027-01-10"
    assert second["candidate_deadline"] == "2028-07-10"
    assert first["latest_review"] is None
    assert second["latest_review"] is None
    assert first["source_state_status"] == "reference_only"

    dashboard = client.get(f"/api/v1/claims/{claim_id}/recovery-timebar/maturity")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert len(body["scenarios"]) == 2
    assert "not findings of liability" in body["disclaimer"]


def test_counterparty_is_human_allegation_context_with_optimistic_append_only_revision() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    created = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties",
        json={
            "name": "TurboMaker GmbH",
            "role": "Potential workshop / service provider",
            "allegation_basis": "Possible workmanship issue identified for investigation only; fault is not determined.",
            "source_reference": "Chief engineer report and overhaul correspondence",
        },
    )
    assert created.status_code == 201, created.text
    v1 = created.json()
    assert v1["version"] == 1
    assert v1["source_state_status"] == "reference_only"

    stale = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties/{v1['counterparty_key']}/revisions",
        json={
            "name": "TurboMaker GmbH",
            "role": "Potential workshop / service provider",
            "allegation_basis": "Updated investigation context without a liability conclusion.",
            "source_reference": "Updated correspondence",
            "expected_record_hash": "0" * 64,
        },
    )
    assert stale.status_code == 409

    revised = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties/{v1['counterparty_key']}/revisions",
        json={
            "name": "TurboMaker GmbH",
            "role": "Potential workshop / service provider",
            "allegation_basis": "Updated investigation context without a liability conclusion.",
            "source_reference": "Updated correspondence",
            "expected_record_hash": v1["record_hash"],
        },
    )
    assert revised.status_code == 201, revised.text
    v2 = revised.json()
    assert v2["version"] == 2
    assert v2["supersedes_id"] == v1["id"]

    history = client.get(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties/{v1['counterparty_key']}/history"
    )
    assert history.status_code == 200
    assert [row["version"] for row in history.json()] == [2, 1]

    with TestingSessionLocal() as db:
        rows = list(db.scalars(select(RecoveryCounterparty).where(
            RecoveryCounterparty.claim_id == UUID(claim_id)
        )))
        assert len(rows) == 2


def test_only_manager_can_confirm_or_override_and_review_hash_chain_is_append_only() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    scenario = _create_scenario(claim_id)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    forbidden = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario['id']}/review",
        json={
            "action": "confirm",
            "scenario_hash": scenario["scenario_hash"],
            "note": "Handler attempted authoritative legal deadline confirmation.",
        },
    )
    assert forbidden.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    confirmed = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario['id']}/review",
        json={
            "action": "confirm",
            "scenario_hash": scenario["scenario_hash"],
            "note": "Manager reviewed the entered basis and confirms this deadline for the controlled claim diary.",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    first = confirmed.json()
    assert first["confirmed_deadline"] == scenario["candidate_deadline"]
    assert first["review_number"] == 1

    overridden = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario['id']}/review",
        json={
            "action": "override",
            "scenario_hash": scenario["scenario_hash"],
            "confirmed_deadline": "2027-02-10",
            "note": "Manager records a separately verified human deadline; the platform did not derive this date.",
            "source_reference": "External counsel advice dated 2026-09-01",
        },
    )
    assert overridden.status_code == 200, overridden.text
    second = overridden.json()
    assert second["review_number"] == 2
    assert second["previous_review_hash"] == first["review_hash"]
    assert second["confirmed_deadline"] == "2027-02-10"

    with TestingSessionLocal() as db:
        rows = list(db.scalars(select(TimebarScenarioReview).where(
            TimebarScenarioReview.scenario_id == UUID(scenario["id"])
        ).order_by(TimebarScenarioReview.review_number.asc())))
        assert len(rows) == 2
        assert rows[0].confirmed_deadline == date(2027, 1, 10)
        assert rows[1].previous_review_hash == rows[0].review_hash


def test_document_evolution_marks_old_scenario_stale_and_requires_deliberate_new_version() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    seed = result["seed"]
    document_v1 = _seed_current_document(claim_id, seed["alpha"].id, seed["admin"].id)

    scenario_v1 = _create_scenario(claim_id, source_document_id=str(document_v1.id))
    assert scenario_v1["source_state_status"] == "current"
    document_v2 = _supersede_document(document_v1, user_id=seed["admin"].id)

    dashboard = client.get(f"/api/v1/claims/{claim_id}/recovery-timebar/maturity")
    assert dashboard.status_code == 200
    stale = next(row for row in dashboard.json()["scenarios"] if row["id"] == scenario_v1["id"])
    assert stale["source_state_status"] == "stale"

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    blocked = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v1['id']}/review",
        json={
            "action": "confirm",
            "scenario_hash": scenario_v1["scenario_hash"],
            "note": "Attempted review after source document supersession.",
        },
    )
    assert blocked.status_code == 409

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    revised = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v1['scenario_key']}/revisions",
        json={
            **_scenario_payload(source_document_id=str(document_v2.id)),
            "expected_scenario_hash": scenario_v1["scenario_hash"],
        },
    )
    assert revised.status_code == 201, revised.text
    scenario_v2 = revised.json()
    assert scenario_v2["version"] == 2
    assert scenario_v2["source_state_status"] == "current"
    assert scenario_v2["supersedes_id"] == scenario_v1["id"]

    history = client.get(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v1['scenario_key']}/history"
    )
    assert history.status_code == 200
    items = history.json()
    assert [row["version"] for row in items] == [2, 1]
    assert items[1]["candidate_deadline"] == scenario_v1["candidate_deadline"]
    assert items[1]["scenario_hash"] == scenario_v1["scenario_hash"]
    assert items[1]["source_state_status"] == "stale"

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    accepted = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v2['id']}/review",
        json={
            "action": "confirm",
            "scenario_hash": scenario_v2["scenario_hash"],
            "note": "Reviewed current replacement contract source and confirms controlled diary deadline.",
        },
    )
    assert accepted.status_code == 200, accepted.text

    with TestingSessionLocal() as db:
        scenarios = list(db.scalars(select(TimebarScenario).where(
            TimebarScenario.claim_id == UUID(claim_id)
        ).order_by(TimebarScenario.version.asc())))
        assert len(scenarios) == 2
        assert scenarios[0].scenario_hash == scenario_v1["scenario_hash"]
