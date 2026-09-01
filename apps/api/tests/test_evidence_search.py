from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import (
    ConfidentialityLevel,
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.evidence_search.models import ClaimEvidenceSearchRun, ClaimEvidenceSearchUnit
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.users.models import User
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_document_processing import PASSWORD, login, seed_claim


def setup_function() -> None:
    reset_database()


def _add_processed_document(
    *,
    claim_id: UUID,
    filename: str,
    document_type: str,
    text: str,
    locator: str,
    family_id: UUID | None = None,
    version: int = 1,
    is_current: bool = True,
    confidentiality: ConfidentialityLevel = ConfidentialityLevel.CONFIDENTIAL,
    supersedes_document_id: UUID | None = None,
) -> UUID:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        assert claim is not None
        uploader = db.scalar(select(User).where(User.organization_id == claim.organization_id))
        assert uploader is not None
        document = Document(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            uploaded_by_id=uploader.id,
            supersedes_document_id=supersedes_document_id,
            document_family_id=family_id or uuid4(),
            filename=filename,
            original_filename=filename,
            document_type=document_type,
            mime_type="text/plain",
            file_size_bytes=len(text.encode("utf-8")),
            file_hash=(f"{filename}:{version}:{text}".encode("utf-8").hex() + "0" * 64)[:64],
            storage_key=f"test/{claim.id}/{filename}/v{version}",
            version_number=version,
            is_current=is_current,
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=confidentiality,
            malware_scan_status=DocumentMalwareScanStatus.CLEAN,
        )
        db.add(document)
        db.flush()
        extraction = DocumentTextExtraction(
            organization_id=claim.organization_id,
            document_id=document.id,
            extraction_method="test-fixture",
            extractor_version="12E-test",
            char_count=len(text),
            segment_count=1,
            requires_ocr=False,
            text_hash=(f"extraction:{document.id}:{text}".encode("utf-8").hex() + "0" * 64)[:64],
            warnings=None,
        )
        db.add(extraction)
        db.flush()
        segment = DocumentTextSegment(
            organization_id=claim.organization_id,
            document_id=document.id,
            extraction_id=extraction.id,
            segment_index=0,
            locator_type="page",
            locator_value=locator,
            text=text,
            char_count=len(text),
        )
        db.add(segment)
        db.commit()
        return document.id


def _search(claim_id: str, query: str, **overrides) -> dict:
    payload = {"query": query, "top_k": 10, "retrieval_mode": "lexical", **overrides}
    response = client.post(f"/api/v1/claims/{claim_id}/evidence-search", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_current_engine_log_hit_returns_exact_source_lineage() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    document_id = _add_processed_document(
        claim_id=claim_id,
        filename="Engine_Log_10_July.txt",
        document_type="engine_log",
        text="10:30 UTC abnormal turbocharger vibration observed. Engine load reduced immediately.",
        locator="4",
    )
    login("alpha", "alpha@example.com")

    result = _search(ids["claim_id"], "abnormal turbocharger vibration")

    assert result["ranking_version"] == "12E.1"
    assert result["retrieval_mode"] == "lexical"
    assert result["semantic_used"] is False
    assert result["semantic_provider"] is None
    assert result["result_count"] == 1
    assert result["no_sufficient_evidence_found"] is False
    row = result["results"][0]
    assert row["document_id"] == str(document_id)
    assert row["document_type"] == "engine_log"
    assert row["document_version"] == 1
    assert row["is_current_document"] is True
    assert row["locator_type"] == "page"
    assert row["locator_value"] == "4"
    assert "abnormal turbocharger vibration" in row["snippet"]
    assert len(row["source_file_hash"]) == 64
    assert len(row["normalized_text_hash"]) == 64
    assert len(row["search_unit_hash"]) == 64
    assert row["semantic_score"] is None


def test_current_version_is_default_and_historical_search_labels_superseded_evidence() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    family_id = uuid4()
    old_id = _add_processed_document(
        claim_id=claim_id,
        filename="PMS_History_v1.txt",
        document_type="pms_history",
        text="Turbocharger overhaul interval recorded at 12000 running hours.",
        locator="1",
        family_id=family_id,
        version=1,
        is_current=False,
    )
    new_id = _add_processed_document(
        claim_id=claim_id,
        filename="PMS_History_v2.txt",
        document_type="pms_history",
        text="Turbocharger overhaul interval revised to 10000 running hours.",
        locator="2",
        family_id=family_id,
        version=2,
        is_current=True,
        supersedes_document_id=old_id,
    )
    login("alpha", "alpha@example.com")

    current = _search(ids["claim_id"], "turbocharger overhaul interval")
    assert [row["document_id"] for row in current["results"]] == [str(new_id)]

    historical = _search(
        ids["claim_id"],
        "turbocharger overhaul interval",
        include_superseded=True,
    )
    assert {row["document_id"] for row in historical["results"]} == {str(old_id), str(new_id)}
    by_id = {row["document_id"]: row for row in historical["results"]}
    assert by_id[str(old_id)]["is_current_document"] is False
    assert by_id[str(new_id)]["is_current_document"] is True


def test_search_is_tenant_and_claim_scoped_in_sql() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="CE_Report.txt",
        document_type="chief_engineer_report",
        text="Alpha-only turbocharger evidence phrase.",
        locator="1",
    )

    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert alpha is not None and beta is not None
        alpha_vessel = db.scalar(select(Vessel).where(Vessel.organization_id == alpha.id))
        beta_vessel = db.scalar(select(Vessel).where(Vessel.organization_id == beta.id))
        assert alpha_vessel is not None and beta_vessel is not None
        other_alpha_claim = Claim(
            organization_id=alpha.id,
            vessel_id=alpha_vessel.id,
            claim_reference="MCRI-HM-2026-0002",
            incident_date=date(2026, 7, 12),
            notification_date=date(2026, 7, 13),
            incident_description="Separate machinery claim",
            currency="USD",
        )
        beta_claim = Claim(
            organization_id=beta.id,
            vessel_id=beta_vessel.id,
            claim_reference="BETA-HM-2026-0001",
            incident_date=date(2026, 7, 12),
            notification_date=date(2026, 7, 13),
            incident_description="Beta machinery claim",
            currency="USD",
        )
        db.add_all([other_alpha_claim, beta_claim])
        db.commit()
        other_alpha_id = other_alpha_claim.id

    _add_processed_document(
        claim_id=other_alpha_id,
        filename="Other_Claim.txt",
        document_type="engine_log",
        text="Cross-claim-secret-keyword appears only in the other Alpha claim.",
        locator="1",
    )

    login("alpha", "alpha@example.com")
    no_leak = _search(ids["claim_id"], "Cross-claim-secret-keyword", retrieval_mode="hybrid")
    assert no_leak["results"] == []

    client.cookies.clear()
    login("beta", "beta@example.com")
    forbidden = client.post(
        f"/api/v1/claims/{ids['claim_id']}/evidence-search",
        json={"query": "turbocharger", "retrieval_mode": "hybrid"},
    )
    assert forbidden.status_code == 404


def test_empty_search_is_explicit_and_does_not_invent_an_answer() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Workshop_Report.txt",
        document_type="workshop_report",
        text="Workshop inspected the removed rotor and bearings.",
        locator="3",
    )
    login("alpha", "alpha@example.com")

    result = _search(ids["claim_id"], "nonexistent cavitation signature", retrieval_mode="hybrid")
    assert result["result_count"] == 0
    assert result["results"] == []
    assert result["no_sufficient_evidence_found"] is True
    assert len(result["result_set_hash"]) == 64


def test_identical_state_and_query_yield_deterministic_ranks_and_result_hash() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Maker_Report.txt",
        document_type="maker_report",
        text="Turbocharger bearing damage noted. Turbocharger rotor inspection recommended.",
        locator="7",
    )
    _add_processed_document(
        claim_id=claim_id,
        filename="Survey_Report.txt",
        document_type="survey_report",
        text="Surveyor noted turbocharger bearing damage and preserved removed parts.",
        locator="5",
    )
    login("alpha", "alpha@example.com")

    first = _search(ids["claim_id"], "turbocharger bearing damage", retrieval_mode="hybrid")
    second = _search(ids["claim_id"], "turbocharger bearing damage", retrieval_mode="hybrid")
    assert first["run_id"] != second["run_id"]
    assert first["ranking_version"] == "12E.2"
    assert first["result_set_hash"] == second["result_set_hash"]
    assert [row["search_unit_id"] for row in first["results"]] == [
        row["search_unit_id"] for row in second["results"]
    ]
    assert [row["combined_score"] for row in first["results"]] == [
        row["combined_score"] for row in second["results"]
    ]


def test_local_hybrid_finds_semantic_equivalent_without_external_provider() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    document_id = _add_processed_document(
        claim_id=claim_id,
        filename="PMS_Overhaul_Record.txt",
        document_type="pms_history",
        text="Turbocharger overhaul completed at 11,800 running hours. Bearings and rotor were inspected.",
        locator="12",
    )
    login("alpha", "alpha@example.com")

    lexical = _search(ids["claim_id"], "When was the machinery last serviced?")
    assert lexical["result_count"] == 0

    hybrid = _search(
        ids["claim_id"],
        "When was the machinery last serviced?",
        retrieval_mode="hybrid",
    )
    assert hybrid["retrieval_mode"] == "hybrid"
    assert hybrid["ranking_version"] == "12E.2"
    assert hybrid["semantic_used"] is True
    assert hybrid["semantic_provider"] == "local_in_process"
    assert hybrid["semantic_model"] == "marine-concepts-hash-v1"
    assert len(hybrid["semantic_authorization_hash"]) == 64
    assert hybrid["result_count"] >= 1
    row = hybrid["results"][0]
    assert row["document_id"] == str(document_id)
    assert row["semantic_score"] is not None and row["semantic_score"] > 0
    assert "local_semantic_concept_match" in row["match_reasons"]

    with TestingSessionLocal() as db:
        run = db.get(ClaimEvidenceSearchRun, UUID(hybrid["run_id"]))
        assert run is not None
        assert run.semantic_provider == "local_in_process"
        assert run.semantic_model == "marine-concepts-hash-v1"
        assert len(run.semantic_authorization_hash or "") == 64


def test_restricted_evidence_can_use_local_hybrid_without_external_egress() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Restricted_Engine_Log.txt",
        document_type="engine_log",
        text="Restricted evidence records 14,250 turbocharger running hours before casualty.",
        locator="9",
        confidentiality=ConfidentialityLevel.RESTRICTED,
    )
    login("alpha", "alpha@example.com")

    result = _search(ids["claim_id"], "operating hours before casualty", retrieval_mode="hybrid")
    assert result["result_count"] == 1
    assert result["semantic_provider"] == "local_in_process"
    assert result["results"][0]["confidentiality_level"] == "restricted"
    assert result["results"][0]["semantic_score"] is not None


def test_search_is_read_only_for_claim_facts_and_search_audit_is_content_free() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="Engine_Log.txt",
        document_type="engine_log",
        text="Evidence records 14,250 turbocharger running hours before casualty.",
        locator="9",
    )
    login("alpha", "alpha@example.com")

    with TestingSessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(ClaimFact).where(ClaimFact.claim_id == claim_id)) or 0

    raw_query = "operating hours before casualty"
    result = _search(ids["claim_id"], raw_query, retrieval_mode="hybrid")
    assert result["result_count"] == 1

    with TestingSessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(ClaimFact).where(ClaimFact.claim_id == claim_id)) or 0
        run = db.get(ClaimEvidenceSearchRun, UUID(result["run_id"]))
        assert run is not None
        assert before == after
        assert run.semantic_provider == "local_in_process"
        assert raw_query not in str(run.filters)
        assert raw_query not in str(run.result_ledger)
        assert len(run.normalized_query_hash) == 64
        unit_table = ClaimEvidenceSearchUnit.__table__
        assert "text" not in unit_table.c

    external = client.post(
        f"/api/v1/claims/{ids['claim_id']}/evidence-search",
        json={"query": "turbocharger", "retrieval_mode": "external_semantic"},
    )
    assert external.status_code == 422


def test_conflicting_passages_are_both_returned_without_resolution() -> None:
    ids = seed_claim()
    claim_id = UUID(ids["claim_id"])
    _add_processed_document(
        claim_id=claim_id,
        filename="CE_Report.txt",
        document_type="chief_engineer_report",
        text="Cause indication: lubrication interruption preceded turbocharger bearing damage.",
        locator="6",
    )
    _add_processed_document(
        claim_id=claim_id,
        filename="Workshop_Report.txt",
        document_type="workshop_report",
        text="Cause indication: foreign object impact preceded turbocharger bearing damage.",
        locator="2",
    )
    login("alpha", "alpha@example.com")

    result = _search(ids["claim_id"], "reason for failure turbocharger bearing damage", retrieval_mode="hybrid")
    assert result["result_count"] == 2
    filenames = {row["document_filename"] for row in result["results"]}
    assert filenames == {"CE_Report.txt", "Workshop_Report.txt"}
