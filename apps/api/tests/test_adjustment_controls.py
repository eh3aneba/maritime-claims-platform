from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.financial.models import CostItem
from app.modules.financial.service import build_financial_review
from app.modules.intelligence.models import DocumentExtraction
from app.modules.intelligence.service import run_invoice_intelligence
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.review.service import review_extraction
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login
from tests.test_financial_intelligence import FP, approve_all, ss


def setup_function() -> None:
    reset_database()


def _invoice_payload(*, supplier: str, number: str, currency: str, lines: list[tuple[str, str, str]]):
    total = sum(Decimal(amount) for _, amount, _ in lines)
    return {
        "classification": {"document_type": "invoice", "confidence": .99},
        "supplier": ss(supplier, supplier),
        "invoice_number": ss(number, number),
        "invoice_date": ss("2026-07-12", "2026-07-12"),
        "purchase_order": ss(None, None, 0),
        "related_quotation_number": ss(None, None, 0),
        "currency": ss(currency, currency),
        "subtotal": ss(f"{total} {currency}", f"{total} {currency}"),
        "tax": ss(None, None, 0),
        "discount": ss(None, None, 0),
        "total": ss(f"{total} {currency}", f"{total} {currency}"),
        "payment_terms": ss(None, None, 0),
        "line_items": [
            {
                "description": ss(description, description),
                "quantity": ss("1", description),
                "unit": ss(None, None, 0),
                "unit_price": ss(f"{amount} {currency}", f"{amount} {currency}"),
                "amount": ss(f"{amount} {currency}", f"{amount} {currency}"),
                "category_candidate": ss(category, description),
                "potential_betterment_cue": {"value": False, "confidence": .99, "source": {"segment_index": 0, "quote": description}},
                "potential_ordinary_maintenance_cue": {"value": False, "confidence": .99, "source": {"segment_index": 0, "quote": description}},
            }
            for description, amount, category in lines
        ],
    }


def _add_reviewed_invoice(
    *,
    claim_id: str,
    user_id: UUID,
    filename: str,
    hash_character: str,
    supplier: str,
    number: str,
    currency: str,
    lines: list[tuple[str, str, str]],
) -> tuple[UUID, UUID]:
    text = f"{supplier} Invoice {number} {currency}. " + " ".join(
        f"{description} {amount} {currency}." for description, amount, _ in lines
    )
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        user = db.get(User, user_id)
        document = Document(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            uploaded_by_id=user.id,
            filename=filename,
            original_filename=filename,
            document_type="invoice",
            mime_type="application/pdf",
            file_size_bytes=100,
            file_hash=hash_character * 64,
            storage_key=f"adjustment/{hash_character}",
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(document)
        db.flush()
        text_extraction = DocumentTextExtraction(
            organization_id=claim.organization_id,
            document_id=document.id,
            extraction_method="test",
            extractor_version="1",
            char_count=len(text),
            segment_count=1,
            requires_ocr=False,
            text_hash=hash_character * 64,
        )
        db.add(text_extraction)
        db.flush()
        db.add(
            DocumentTextSegment(
                organization_id=claim.organization_id,
                document_id=document.id,
                extraction_id=text_extraction.id,
                segment_index=0,
                locator_type="page",
                locator_value="1",
                text=text,
                char_count=len(text),
            )
        )
        db.flush()
        run = run_invoice_intelligence(
            db,
            document=document,
            requested_by_id=user.id,
            provider=FP(
                _invoice_payload(
                    supplier=supplier,
                    number=number,
                    currency=currency,
                    lines=lines,
                )
            ),
        )
        approve_all(db, run, user)
        db.commit()
        return document.id, run.id


def _seed_cost_schedule(*, include_eur: bool = False) -> tuple[str, list[str], dict[str, UUID]]:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    admin_id = result["seed"]["admin"].id
    document_id, run_id = _add_reviewed_invoice(
        claim_id=claim_id,
        user_id=admin_id,
        filename="invoice-usd.pdf",
        hash_character="a",
        supplier="Turbo Repair Ltd",
        number="INV-100",
        currency="USD",
        lines=[
            ("Turbocharger rotor repair", "1000.00", "Permanent Repair"),
            ("Technician attendance and testing", "500.00", "Attendance"),
        ],
    )
    refs = {"usd_document_id": document_id, "usd_run_id": run_id}
    if include_eur:
        eur_document, eur_run = _add_reviewed_invoice(
            claim_id=claim_id,
            user_id=admin_id,
            filename="invoice-eur.pdf",
            hash_character="b",
            supplier="European Service GmbH",
            number="INV-EUR-1",
            currency="EUR",
            lines=[("Specialist attendance", "500.00", "Attendance")],
        )
        refs.update({"eur_document_id": eur_document, "eur_run_id": eur_run})

    with TestingSessionLocal() as db:
        review = build_financial_review(
            db,
            claim=db.get(Claim, UUID(claim_id)),
            user_id=admin_id,
        )
        db.commit()
        usd_ids = [
            str(row["id"])
            for row in review["items"]
            if row["document_id"] == document_id
        ]
    return claim_id, usd_ids, refs


def _edit_invoice_amount(*, run_id: UUID, field_path: str, value: str, user_email: str = "alpha-admin@example.com") -> None:
    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.email == user_email))
        extraction = db.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.ai_run_id == run_id,
                DocumentExtraction.field_path == field_path,
            )
        )
        review_extraction(
            db,
            extraction=extraction,
            reviewer=user,
            action="edit",
            value={"value": float(Decimal(value)), "currency": "USD", "raw": f"{value} USD"},
            reason="Phase 13.6B source-evolution acceptance correction.",
            confirm_re_review=True,
        )
        db.commit()


def _treat_all_lines(claim_id: str, statement: dict) -> dict:
    current = statement
    for line in statement["lines"]:
        current = client.patch(
            f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{line['id']}",
            json={
                "treatment": "included",
                "basis": "particular_average",
                "considered_amount": line["claimed_amount"],
                "note": "Human-reviewed casualty adjustment treatment.",
            },
        ).json()
    return current


def test_adjustment_is_state_bound_versioned_human_reviewed_and_immutable() -> None:
    claim_id, cost_ids, refs = _seed_cost_schedule()
    created = client.post(
        f"/api/v1/claims/{claim_id}/adjustments",
        json={"currency": "usd", "title": "MT ORION – H&M Adjustment Draft"},
    )
    assert created.status_code == 201, created.text
    statement = created.json()
    assert statement["version"] == 1
    assert statement["status"] == "draft"
    assert statement["source_state_status"] == "current"
    assert len(statement["source_state_hash"]) == 64
    assert statement["source_state_hash"] == statement["current_source_state_hash"]
    assert statement["gross_claimed"] == "1500.00"
    assert len(statement["lines"]) == 2
    assert {line["cost_item_id"] for line in statement["lines"]} == set(cost_ids)

    blocked = client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit")
    assert blocked.status_code == 409
    assert "treatment is pending" in blocked.json()["detail"]

    first, second = statement["lines"]
    updated = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{first['id']}",
        json={
            "treatment": "included",
            "basis": "particular_average",
            "considered_amount": "1000.00",
            "note": "Casualty repair cost supported by reviewed invoice.",
            "financial_controls": {
                "betterment": {
                    "percentage": "10",
                    "amount": "100.00",
                    "basis": "Human reviewer records an upgrade element for consideration only.",
                    "source_reference": "Reviewed repair scope comparison in claim file.",
                }
            },
        },
    )
    assert updated.status_code == 200, updated.text
    first_after = next(row for row in updated.json()["lines"] if row["id"] == first["id"])
    assert first_after["financial_controls"]["betterment"]["computed_reference_amount"] == "100.00"

    updated = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{second['id']}",
        json={
            "treatment": "apportioned",
            "basis": "general_average",
            "considered_amount": "300.00",
            "reason": "USD 200 relates to non-common-safety attendance.",
        },
    )
    assert updated.status_code == 200, updated.text
    updated = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}",
        json={
            "deductible_amount": "100.00",
            "deductible_basis": "Policy deductible subject to final wording review.",
            "other_deduction_amount": "50.00",
            "other_deduction_basis": "Agreed residual value credit.",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["gross_considered"] == "1300.00"
    assert updated.json()["net_adjusted"] == "1150.00"

    submitted = client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "under_review"

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Handler must not approve."},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Line treatments, bases and deductions reviewed against the current source-bound claim file."},
    )
    assert approved.status_code == 200, approved.text
    approved_payload = approved.json()
    assert approved_payload["status"] == "approved"
    assert len(approved_payload["content_hash"]) == 64

    immutable = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}",
        json={"deductible_amount": "0.00"},
    )
    assert immutable.status_code == 409

    _edit_invoice_amount(
        run_id=refs["usd_run_id"],
        field_path="invoice.line_items[0].amount",
        value="1100.00",
        user_email="alpha-admin@example.com",
    )
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    preserved = client.get(f"/api/v1/claims/{claim_id}/adjustments").json()["items"][0]
    assert preserved["gross_claimed"] == "1500.00"
    assert preserved["lines"][0]["claimed_amount"] == "1000.00"
    assert preserved["source_state_status"] == "stale"
    assert preserved["source_change_summary"]["changed_count"] == 1

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.entity_id == UUID(statement["id"]))))
        assert {
            "CREATE_ADJUSTMENT_STATEMENT",
            "SUBMIT_ADJUSTMENT_FOR_REVIEW",
            "APPROVE_ADJUSTMENT_STATEMENT",
        }.issubset(actions)


def test_stale_adjustment_requires_explicit_rebase_and_only_carries_unchanged_line_judgment() -> None:
    claim_id, _, refs = _seed_cost_schedule()
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    statement = _treat_all_lines(claim_id, statement)
    changed_line = next(line for line in statement["lines"] if line["source_snapshot"]["line_index"] == 0)
    unchanged_line = next(line for line in statement["lines"] if line["source_snapshot"]["line_index"] == 1)
    statement = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}",
        json={
            "deductible_amount": "100.00",
            "deductible_basis": "Human-entered deductible for this version.",
        },
    ).json()

    _edit_invoice_amount(
        run_id=refs["usd_run_id"],
        field_path="invoice.line_items[0].amount",
        value="1200.00",
    )

    stale = client.get(f"/api/v1/claims/{claim_id}/adjustments").json()["items"][0]
    assert stale["source_state_status"] == "stale"
    assert stale["source_change_summary"]["changed_count"] == 1
    assert client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}",
        json={"deductible_amount": "50.00"},
    ).status_code == 409
    assert client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit").status_code == 409

    rebased = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/rebase",
        json={
            "carry_statement_controls": False,
            "note": "Explicitly rebase to the corrected invoice evidence; changed lines require fresh review.",
        },
    )
    assert rebased.status_code == 201, rebased.text
    current = rebased.json()
    assert current["version"] == 2
    assert current["rebased_from_statement_id"] == statement["id"]
    assert current["source_state_status"] == "current"
    assert current["deductible_amount"] == "0.00"
    changed = next(line for line in current["lines"] if line["source_snapshot"]["line_index"] == 0)
    unchanged = next(line for line in current["lines"] if line["source_snapshot"]["line_index"] == 1)
    assert changed["claimed_amount"] == "1200.00"
    assert changed["treatment"] == "pending"
    assert changed["basis"] == "unallocated"
    assert changed["considered_amount"] == "0.00"
    assert unchanged["source_snapshot"]["item_key"] == unchanged_line["source_snapshot"]["item_key"]
    assert unchanged["treatment"] == "included"
    assert unchanged["considered_amount"] == "500.00"
    assert changed["source_snapshot"]["item_key"] == changed_line["source_snapshot"]["item_key"]


def test_under_review_statement_cannot_be_approved_after_financial_source_changes() -> None:
    claim_id, _, refs = _seed_cost_schedule()
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    _treat_all_lines(claim_id, statement)
    submitted = client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit")
    assert submitted.status_code == 200

    _edit_invoice_amount(
        run_id=refs["usd_run_id"],
        field_path="invoice.line_items[0].amount",
        value="1250.00",
    )
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    blocked = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Stale source must block approval."},
    )
    assert blocked.status_code == 409
    assert "source evidence has changed" in blocked.json()["detail"]


def test_cross_currency_line_requires_human_entered_fx_rate_date_source_and_exact_math() -> None:
    claim_id, _, _ = _seed_cost_schedule(include_eur=True)
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    eur_line = next(line for line in statement["lines"] if line["source_snapshot"]["source_currency"] == "EUR")
    assert eur_line["claimed_amount"] == "0.00"

    missing_fx = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{eur_line['id']}",
        json={
            "treatment": "included",
            "basis": "particular_average",
            "claimed_amount": "600.00",
            "considered_amount": "600.00",
        },
    )
    assert missing_fx.status_code == 422
    assert "FX rate" in missing_fx.json()["detail"]

    wrong_math = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{eur_line['id']}",
        json={
            "treatment": "included",
            "basis": "particular_average",
            "claimed_amount": "650.00",
            "considered_amount": "650.00",
            "financial_controls": {
                "fx": {
                    "rate": "1.20",
                    "source_currency": "EUR",
                    "target_currency": "USD",
                    "rate_date": "2026-07-12",
                    "source_reference": "Human-checked bank FX confirmation dated 2026-07-12.",
                }
            },
        },
    )
    assert wrong_math.status_code == 422

    valid = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{eur_line['id']}",
        json={
            "treatment": "included",
            "basis": "particular_average",
            "claimed_amount": "600.00",
            "considered_amount": "600.00",
            "financial_controls": {
                "fx": {
                    "rate": "1.20",
                    "source_currency": "EUR",
                    "target_currency": "USD",
                    "rate_date": "2026-07-12",
                    "source_reference": "Human-checked bank FX confirmation dated 2026-07-12.",
                }
            },
        },
    )
    assert valid.status_code == 200, valid.text
    line = next(row for row in valid.json()["lines"] if row["id"] == eur_line["id"])
    assert line["claimed_amount"] == "600.00"
    assert line["financial_controls"]["fx"]["rate"] == "1.20"
    assert line["financial_controls"]["fx"]["source_reference"].startswith("Human-checked")


def test_adjustment_rejects_invalid_line_math_and_is_tenant_scoped() -> None:
    claim_id, _, _ = _seed_cost_schedule()
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    line = statement["lines"][0]
    invalid = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{line['id']}",
        json={
            "treatment": "apportioned",
            "basis": "particular_average",
            "considered_amount": "2000.00",
            "reason": "Invalid amount",
        },
    )
    assert invalid.status_code == 422

    inconsistent_control = client.patch(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/lines/{line['id']}",
        json={
            "treatment": "included",
            "basis": "particular_average",
            "considered_amount": line["claimed_amount"],
            "financial_controls": {
                "depreciation": {
                    "percentage": "10",
                    "amount": "999.00",
                    "basis": "Human-entered depreciation hypothesis for review.",
                    "source_reference": "Surveyor age/condition note.",
                }
            },
        },
    )
    assert inconsistent_control.status_code == 422

    client.cookies.clear()
    login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/adjustments").status_code == 404
    assert client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).status_code == 404
