from datetime import date

from sqlalchemy import select

from app.ai.gateway.base import AIRequest, AIResponse
from app.core.security import hash_password
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.financial.service import build_financial_review
from app.modules.intelligence.models import DocumentExtraction
from app.modules.intelligence.service import run_invoice_intelligence, run_quotation_intelligence
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.review.service import review_extraction
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database

PASSWORD = "x"


def ss(value, quote, confidence=.98):
    return {
        "value": value,
        "confidence": confidence,
        "source": {"segment_index": 0 if value is not None else None, "quote": quote},
    }


def sb(value, quote, confidence=.98):
    return {
        "value": value,
        "confidence": confidence,
        "source": {"segment_index": 0 if value is not None else None, "quote": quote},
    }


class FP:
    name = "fake"
    _model = "fake-fin-v1"

    def __init__(self, payload):
        self.payload = payload

    def generate(self, request: AIRequest):
        return AIResponse(
            provider="fake",
            model=self._model,
            structured_output=self.payload,
            output_text="{}",
            usage={},
            raw_response_id="x",
        )


def setup_function():
    reset_database()


def seed(document_type, text, hash_character):
    with TestingSessionLocal() as db:
        organization = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        if not organization:
            organization = Organization(name="Alpha", slug="alpha")
            db.add(organization)
            db.flush()
            user = User(
                organization_id=organization.id,
                email="h@x.com",
                full_name="H",
                password_hash=hash_password(PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            )
            vessel = Vessel(
                organization_id=organization.id,
                name="MT ORION",
                imo_number="7000301",
            )
            db.add_all([user, vessel])
            db.flush()
            claim = Claim(
                organization_id=organization.id,
                vessel_id=vessel.id,
                claim_reference="MCRI-HM-2026-0001",
                incident_date=date(2026, 7, 10),
                notification_date=date(2026, 7, 11),
                incident_description="Main engine turbocharger failure",
                currency="USD",
                status=ClaimStatus.FINANCIAL_REVIEW,
            )
            db.add(claim)
            db.flush()
        else:
            user = db.scalar(select(User).where(User.organization_id == organization.id))
            claim = db.scalar(select(Claim).where(Claim.organization_id == organization.id))

        document = Document(
            organization_id=organization.id,
            claim_id=claim.id,
            uploaded_by_id=user.id,
            filename=document_type + ".pdf",
            original_filename=document_type + ".pdf",
            document_type=document_type,
            mime_type="application/pdf",
            file_size_bytes=100,
            file_hash=hash_character * 64,
            storage_key="x/" + hash_character,
            processing_status=DocumentProcessingStatus.PROCESSED,
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(document)
        db.flush()
        extraction = DocumentTextExtraction(
            organization_id=organization.id,
            document_id=document.id,
            extraction_method="test",
            extractor_version="1",
            char_count=len(text),
            segment_count=1,
            requires_ocr=False,
            text_hash=hash_character * 64,
        )
        db.add(extraction)
        db.flush()
        db.add(
            DocumentTextSegment(
                organization_id=organization.id,
                document_id=document.id,
                extraction_id=extraction.id,
                segment_index=0,
                locator_type="page",
                locator_value="1",
                text=text,
                char_count=len(text),
            )
        )
        db.commit()
        return claim.id, document.id, user.id


def approve_all(db, run, user):
    for extraction in db.scalars(
        select(DocumentExtraction).where(DocumentExtraction.ai_run_id == run.id)
    ):
        review_extraction(
            db,
            extraction=extraction,
            reviewer=user,
            action="approve",
            reason="reviewed source",
        )
    db.commit()


def test_invoice_materializes_cost_and_predate_flag():
    text = "ABC Invoice INV-1 dated 2026-07-01 USD. Rotor assembly 240,000 USD. Total 240,000 USD."
    claim_id, document_id, user_id = seed("invoice", text, "a")
    payload = {
        "classification": {"document_type": "invoice", "confidence": .99},
        "supplier": ss("ABC", "ABC"),
        "invoice_number": ss("INV-1", "INV-1"),
        "invoice_date": ss("2026-07-01", "2026-07-01"),
        "purchase_order": ss(None, None, 0),
        "related_quotation_number": ss(None, None, 0),
        "currency": ss("USD", "USD"),
        "subtotal": ss("240,000 USD", "240,000 USD"),
        "tax": ss(None, None, 0),
        "discount": ss(None, None, 0),
        "total": ss("240,000 USD", "Total 240,000 USD"),
        "payment_terms": ss(None, None, 0),
        "line_items": [
            {
                "description": ss("Rotor assembly", "Rotor assembly"),
                "quantity": ss("1", "Rotor assembly 240,000 USD"),
                "unit": ss(None, None, 0),
                "unit_price": ss("240,000 USD", "240,000 USD"),
                "amount": ss("240,000 USD", "240,000 USD"),
                "category_candidate": ss("Spare Parts", "Rotor assembly"),
                "potential_betterment_cue": sb(False, "Rotor assembly"),
                "potential_ordinary_maintenance_cue": sb(False, "Rotor assembly"),
            }
        ],
    }
    with TestingSessionLocal() as db:
        run = run_invoice_intelligence(
            db,
            document=db.get(Document, document_id),
            requested_by_id=user_id,
            provider=FP(payload),
        )
        approve_all(db, run, db.get(User, user_id))
        review = build_financial_review(
            db,
            claim=db.get(Claim, claim_id),
            user_id=user_id,
        )
        db.commit()
        assert str(review["items"][0]["amount"]) == "240000.00"
        assert review["items"][0]["source_state"] == "current_usable"
        assert any(flag.flag_type.value == "invoice_predates_incident" for flag in review["flags"])


def test_quote_scope_difference_flag():
    quote_one = "ABC Quote Q1 USD 260000 Rotor repair scope. Total 260000."
    claim_id, document_one, user_id = seed("quotation", quote_one, "b")
    quote_two = "XYZ Quote Q2 USD 470000 Complete turbocharger replacement. Total 470000."
    _, document_two, _ = seed("quotation", quote_two, "c")

    def payload(supplier, number, total, scope):
        return {
            "classification": {"document_type": "quotation", "confidence": .99},
            "supplier": ss(supplier, supplier),
            "quotation_number": ss(number, number),
            "quotation_date": ss("2026-07-12", "2026-07-12"),
            "currency": ss("USD", "USD"),
            "subtotal": ss(str(total), str(total)),
            "tax": ss(None, None, 0),
            "freight": ss(None, None, 0),
            "total": ss(str(total), str(total)),
            "validity": ss(None, None, 0),
            "lead_time": ss(None, None, 0),
            "repair_duration": ss(None, None, 0),
            "scope_summary": ss(scope, scope),
            "exclusions": [],
            "line_items": [
                {
                    "description": ss(scope, scope),
                    "quantity": ss("1", scope),
                    "unit": ss(None, None, 0),
                    "unit_price": ss(str(total), str(total)),
                    "amount": ss(str(total), str(total)),
                    "category_candidate": ss("Permanent Repair", scope),
                    "potential_betterment_cue": sb(False, scope),
                    "potential_ordinary_maintenance_cue": sb(False, scope),
                }
            ],
        }

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        first_run = run_quotation_intelligence(
            db,
            document=db.get(Document, document_one),
            requested_by_id=user_id,
            provider=FP(payload("ABC", "Q1", 260000, "Rotor repair scope")),
        )
        approve_all(db, first_run, user)
        second_run = run_quotation_intelligence(
            db,
            document=db.get(Document, document_two),
            requested_by_id=user_id,
            provider=FP(payload("XYZ", "Q2", 470000, "Complete turbocharger replacement")),
        )
        approve_all(db, second_run, user)
        review = build_financial_review(
            db,
            claim=db.get(Claim, claim_id),
            user_id=user_id,
        )
        db.commit()
        assert len(review["quotations"]) == 2
        assert any(flag.flag_type.value == "quote_scope_difference" for flag in review["flags"])
