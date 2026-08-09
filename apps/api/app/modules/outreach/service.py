from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.outreach.models import DesignPartnerAccount, DesignPartnerContact, OutreachTouch, PaidPilotOffer
from app.modules.outreach.scoring import calculate_qualification_score, qualification_band, recommended_action


def _score_payload(row_or_values):
    return {field: getattr(row_or_values, field, None) if not isinstance(row_or_values, dict) else row_or_values.get(field) for field in (
        "machinery_claim_volume_score","pain_intensity_score","buyer_access_score","data_availability_score","security_fit_score","pilot_willingness_score"
    )}


def create_account(db: Session, *, organization_id, payload):
    values = payload.model_dump()
    score = calculate_qualification_score(values)
    row = DesignPartnerAccount(organization_id=organization_id, qualification_score=score, qualification_rationale=recommended_action(score, "prospect"), **values)
    db.add(row); db.flush()
    return row


def update_account(db: Session, *, row, payload):
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(row, key, value)
    score = calculate_qualification_score(_score_payload(row))
    row.qualification_score = score
    row.qualification_rationale = recommended_action(score, row.stage)
    db.flush(); return row


def build_cohort_summary(db: Session, *, organization_id):
    rows = list(db.scalars(select(DesignPartnerAccount).where(DesignPartnerAccount.organization_id == organization_id).order_by(DesignPartnerAccount.qualification_score.desc(), DesignPartnerAccount.created_at.asc())))
    accounts = []
    for row in rows:
        accounts.append({**{c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in {"organization_id","website","source","notes","updated_at"}}, "qualification_band": qualification_band(row.qualification_score), "recommended_action": recommended_action(row.qualification_score, row.stage)})
    pilot_qualified = sum(1 for r in rows if r.stage in {"pilot_qualified","pilot_proposed","pilot_active","paid_pilot","customer"})
    paid = sum(1 for r in rows if r.stage in {"paid_pilot","customer"})
    return {"target_qualified_partners": 3, "target_paid_pilots": 1, "accounts_total": len(rows), "a_tier": sum(1 for r in rows if qualification_band(r.qualification_score)=="A"), "b_tier": sum(1 for r in rows if qualification_band(r.qualification_score)=="B"), "pilot_qualified": pilot_qualified, "paid_pilots": paid, "target_progress": {"qualified": min(pilot_qualified,3), "paid": min(paid,1)}, "accounts": accounts}


def next_offer_version(db: Session, *, organization_id, account_id):
    current = db.scalar(select(func.max(PaidPilotOffer.version)).where(PaidPilotOffer.organization_id == organization_id, PaidPilotOffer.account_id == account_id)) or 0
    return current + 1
