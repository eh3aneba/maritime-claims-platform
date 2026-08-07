from __future__ import annotations
import hashlib, re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem, CostReviewStatus, FinancialFlag, FinancialFlagStatus, FinancialFlagType, ReserveHistory
from app.modules.intelligence.models import AIRun, AIReviewStatus, DocumentExtraction

_REVIEWED=(AIReviewStatus.APPROVED,AIReviewStatus.EDITED)

def _val(row: DocumentExtraction | None):
    if row is None: return None
    return row.approved_value if row.human_status==AIReviewStatus.EDITED else (row.normalized_value if row.normalized_value is not None else row.raw_value)

def _as_text(value: Any) -> str | None:
    if value is None: return None
    if isinstance(value, dict) and "raw" in value: return str(value["raw"])
    return str(value)

def _decimal(value: Any) -> Decimal | None:
    if value is None: return None
    if isinstance(value, dict): value=value.get("value")
    if isinstance(value,(int,float,Decimal)):
        return Decimal(str(value))
    text=str(value).strip()
    # strip currency symbols/codes and tolerate thousand separators
    token=re.search(r"[-+]?\d[\d,.]*",text)
    if not token:return None
    raw=token.group(0)
    if raw.count(",") and raw.count("."):
        if raw.rfind(".")>raw.rfind(","): raw=raw.replace(",","")
        else: raw=raw.replace(".","").replace(",",".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?",raw): raw=raw.replace(",","")
    elif raw.count(",")==1 and len(raw.split(",")[-1])<=2: raw=raw.replace(",",".")
    else: raw=raw.replace(",","")
    try:return Decimal(raw)
    except InvalidOperation:return None

def _date(value: Any) -> date | None:
    if not value:return None
    try:return date.fromisoformat(str(value))
    except ValueError:return None

def _reviewed_rows(db:Session, run:AIRun)->dict[str,DocumentExtraction]:
    return {x.field_path:x for x in db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id==run.id,DocumentExtraction.human_status.in_(_REVIEWED)))}

def _latest_completed_runs(db:Session, claim:Claim, tasks:list[str])->list[AIRun]:
    all_runs=list(db.scalars(select(AIRun).where(AIRun.claim_id==claim.id,AIRun.organization_id==claim.organization_id,AIRun.task.in_(tasks),AIRun.status=="completed").order_by(AIRun.created_at.desc())))
    seen=set(); out=[]
    for r in all_runs:
        if r.document_id in seen:continue
        seen.add(r.document_id);out.append(r)
    return out

def sync_financial_review(db:Session, *, claim:Claim, user_id:UUID|None=None)->None:
    from app.modules.intelligence.service import TASK_QUOTATION, TASK_INVOICE
    runs=_latest_completed_runs(db,claim,[TASK_QUOTATION,TASK_INVOICE])
    active_run_ids={r.id for r in runs}
    # Rebuild derived cost items from current reviewed evidence. Status preservation by stable key.
    existing={(x.ai_run_id,x.source_field_prefix):x for x in db.scalars(select(CostItem).where(CostItem.claim_id==claim.id,CostItem.organization_id==claim.organization_id))}
    keep=set()
    for run in runs:
        rows=_reviewed_rows(db,run)
        kind="quotation" if run.task==TASK_QUOTATION else "invoice"
        prefix="quotation.line_items" if kind=="quotation" else "invoice.line_items"
        supplier=_as_text(_val(rows.get(f"{kind}.supplier")))
        num_field="quotation_number" if kind=="quotation" else "invoice_number"
        date_field="quotation_date" if kind=="quotation" else "invoice_date"
        number=_as_text(_val(rows.get(f"{kind}.{num_field}")))
        doc_date=_date(_val(rows.get(f"{kind}.{date_field}")))
        currency=(_as_text(_val(rows.get(f"{kind}.currency"))) or claim.currency).upper()[:3]
        indices=sorted({int(m.group(1)) for p in rows for m in [re.match(rf"^{re.escape(prefix)}\[(\d+)\]\.description$",p)] if m})
        for i in indices:
            base=f"{prefix}[{i}]"
            desc=_as_text(_val(rows.get(base+".description")))
            amount=_decimal(_val(rows.get(base+".amount")))
            if not desc or amount is None or amount<0:continue
            key=(run.id,base);keep.add(key)
            item=existing.get(key)
            if item is None:
                item=CostItem(organization_id=claim.organization_id,claim_id=claim.id,document_id=run.document_id,ai_run_id=run.id,line_index=i,document_kind=kind,description=desc,amount=amount,currency=currency,source_field_prefix=base,review_status=CostReviewStatus.UNDER_REVIEW)
                db.add(item)
            item.supplier=supplier;item.document_number=number;item.document_date=doc_date;item.description=desc;item.amount=amount;item.currency=currency
            item.quantity=_decimal(_val(rows.get(base+".quantity")));item.unit=_as_text(_val(rows.get(base+".unit")));item.unit_price=_decimal(_val(rows.get(base+".unit_price")));item.category=_as_text(_val(rows.get(base+".category_candidate")))
    for key,item in existing.items():
        if key not in keep: db.delete(item)
    db.flush()
    _sync_flags(db,claim=claim,runs=runs)
    write_audit_log(db,organization_id=claim.organization_id,user_id=user_id,action="SYNC_FINANCIAL_REVIEW",entity_type="claim",entity_id=claim.id,new_values={"source_runs":len(runs)})

def _upsert_flag(db:Session,claim:Claim,*,flag_type:FinancialFlagType,fingerprint:str,severity:str,title:str,explanation:str,evidence:dict):
    row=db.scalar(select(FinancialFlag).where(FinancialFlag.claim_id==claim.id,FinancialFlag.organization_id==claim.organization_id,FinancialFlag.fingerprint==fingerprint))
    if row is None:
        row=FinancialFlag(organization_id=claim.organization_id,claim_id=claim.id,flag_type=flag_type,fingerprint=fingerprint,severity=severity,title=title,explanation=explanation,evidence=evidence)
        db.add(row)
    else:
        row.severity=severity;row.title=title;row.explanation=explanation;row.evidence=evidence
    return row

def _sync_flags(db:Session,*,claim:Claim,runs:list[AIRun]):
    from app.modules.intelligence.service import TASK_QUOTATION,TASK_INVOICE
    live=set()
    headers=[]
    for run in runs:
        rows=_reviewed_rows(db,run); kind="quotation" if run.task==TASK_QUOTATION else "invoice"
        number=_as_text(_val(rows.get(f"{kind}.{'quotation_number' if kind=='quotation' else 'invoice_number'}")))
        supplier=_as_text(_val(rows.get(f"{kind}.supplier"))); total=_decimal(_val(rows.get(f"{kind}.total"))); d=_date(_val(rows.get(f"{kind}.{'quotation_date' if kind=='quotation' else 'invoice_date'}")))
        headers.append((run,kind,number,supplier,total,d,rows))
        if kind=="invoice" and d and d<claim.incident_date:
            fp=f"invoice-date:{run.document_id}";live.add(fp);_upsert_flag(db,claim,flag_type=FinancialFlagType.INVOICE_PREDATES_INCIDENT,fingerprint=fp,severity="medium",title="Invoice predates reported casualty",explanation="The reviewed invoice date is earlier than the claim incident date. Review whether this is an advance/previous transaction or data issue; do not reject automatically.",evidence={"invoice_date":d.isoformat(),"incident_date":claim.incident_date.isoformat(),"document_id":str(run.document_id)})
        prefix=f"{kind}.line_items"
        indices=sorted({int(m.group(1)) for p in rows for m in [re.match(rf"^{re.escape(prefix)}\[(\d+)\]\.description$",p)] if m})
        for i in indices:
            for leaf,ft,title in [("potential_betterment_cue",FinancialFlagType.POTENTIAL_BETTERMENT,"Potential betterment / upgrade cue"),("potential_ordinary_maintenance_cue",FinancialFlagType.POTENTIAL_ORDINARY_MAINTENANCE,"Potential ordinary maintenance item")]:
                if _val(rows.get(f"{prefix}[{i}].{leaf}")) is True:
                    fp=f"{ft.value}:{run.id}:{i}";live.add(fp);desc=_as_text(_val(rows.get(f"{prefix}[{i}].description")))
                    _upsert_flag(db,claim,flag_type=ft,fingerprint=fp,severity="medium",title=title,explanation="This is a review cue from human-reviewed source evidence, not a recoverability decision.",evidence={"document_id":str(run.document_id),"line_index":i,"description":desc})
    # probable duplicate invoices on strong header match
    invoices=[h for h in headers if h[1]=="invoice"]
    for i,a in enumerate(invoices):
        for b in invoices[i+1:]:
            if a[2] and b[2] and a[3] and b[3] and a[2].casefold()==b[2].casefold() and a[3].casefold()==b[3].casefold() and a[4] is not None and a[4]==b[4]:
                ids=sorted([str(a[0].document_id),str(b[0].document_id)]);fp="duplicate:"+hashlib.sha1("|".join(ids).encode()).hexdigest();live.add(fp)
                _upsert_flag(db,claim,flag_type=FinancialFlagType.POSSIBLE_DUPLICATE,fingerprint=fp,severity="high",title="Probable duplicate invoice",explanation="Reviewed supplier, invoice number and total match across two invoice documents. Human review is required before any duplicate conclusion.",evidence={"document_ids":ids,"invoice_number":a[2],"supplier":a[3],"total":str(a[4])})
    # quote scope difference when >=2 reviewed quotes and normalized scope differs
    quotes=[h for h in headers if h[1]=="quotation"]
    if len(quotes)>=2:
        scopes=[]
        for h in quotes:
            scope=_as_text(_val(h[6].get("quotation.scope_summary")))
            if scope:scopes.append((h,scope))
        if len(scopes)>=2 and len({re.sub(r"\s+"," ",s.casefold()).strip() for _,s in scopes})>1:
            ids=sorted(str(h[0].document_id) for h,_ in scopes);fp="quote-scope:"+hashlib.sha1("|".join(ids).encode()).hexdigest();live.add(fp)
            _upsert_flag(db,claim,flag_type=FinancialFlagType.QUOTE_SCOPE_DIFFERENCE,fingerprint=fp,severity="high",title="Material quotation scope difference",explanation="Reviewed quotation scopes are not the same. Technical justification is required before price-only comparison; the system does not select a supplier.",evidence={"quotes":[{"document_id":str(h[0].document_id),"supplier":h[3],"scope":s,"total":str(h[4]) if h[4] is not None else None} for h,s in scopes]})
    # stale open derived flags become irrelevant, preserving audit/history.
    for flag in db.scalars(select(FinancialFlag).where(FinancialFlag.claim_id==claim.id,FinancialFlag.organization_id==claim.organization_id,FinancialFlag.status==FinancialFlagStatus.OPEN)):
        if flag.fingerprint not in live:
            flag.status=FinancialFlagStatus.IRRELEVANT;flag.resolution_note="Underlying reviewed evidence no longer triggers this deterministic flag.";flag.resolved_at=datetime.now(UTC)

def build_financial_review(db:Session,*,claim:Claim,user_id:UUID|None=None)->dict[str,Any]:
    sync_financial_review(db,claim=claim,user_id=user_id);db.flush()
    items=list(db.scalars(select(CostItem).where(CostItem.claim_id==claim.id,CostItem.organization_id==claim.organization_id).order_by(CostItem.created_at.asc())))
    flags=list(db.scalars(select(FinancialFlag).where(FinancialFlag.claim_id==claim.id,FinancialFlag.organization_id==claim.organization_id).order_by(FinancialFlag.created_at.desc())))
    reserves=list(db.scalars(select(ReserveHistory).where(ReserveHistory.claim_id==claim.id,ReserveHistory.organization_id==claim.organization_id).order_by(ReserveHistory.created_at.desc())))
    totals={}
    for x in items:
        if x.document_kind!="invoice": continue
        totals[x.currency]=totals.get(x.currency,Decimal("0"))+x.amount
    quotations=[]
    from app.modules.intelligence.service import TASK_QUOTATION
    for run in _latest_completed_runs(db,claim,[TASK_QUOTATION]):
        rows=_reviewed_rows(db,run)
        line_items=[]
        for item in items:
            if item.ai_run_id==run.id:
                line_items.append({"description":item.description,"amount":str(item.amount),"currency":item.currency,"category":item.category})
        quotations.append({"document_id":run.document_id,"supplier":_as_text(_val(rows.get("quotation.supplier"))),"quotation_number":_as_text(_val(rows.get("quotation.quotation_number"))),"currency":_as_text(_val(rows.get("quotation.currency"))),"total":_decimal(_val(rows.get("quotation.total"))),"scope_summary":_as_text(_val(rows.get("quotation.scope_summary"))),"lead_time":_as_text(_val(rows.get("quotation.lead_time"))),"repair_duration":_as_text(_val(rows.get("quotation.repair_duration"))),"line_items":line_items})
    return {"claim_id":claim.id,"totals_by_currency":totals,"items":items,"flags":flags,"quotations":quotations,"reserve_history":reserves}

def update_cost_status(db:Session,*,claim:Claim,item:CostItem,status:CostReviewStatus,reason:str,user_id:UUID):
    old=item.review_status.value;item.review_status=status
    write_audit_log(db,organization_id=claim.organization_id,user_id=user_id,action="CHANGE_COST_REVIEW_STATUS",entity_type="cost_item",entity_id=item.id,old_values={"status":old},new_values={"status":status.value,"reason":reason})

def resolve_financial_flag(db:Session,*,claim:Claim,flag:FinancialFlag,status:FinancialFlagStatus,note:str,user_id:UUID):
    old=flag.status.value;flag.status=status;flag.resolution_note=note;flag.resolved_by_id=user_id;flag.resolved_at=datetime.now(UTC)
    write_audit_log(db,organization_id=claim.organization_id,user_id=user_id,action="RESOLVE_FINANCIAL_FLAG",entity_type="financial_flag",entity_id=flag.id,old_values={"status":old},new_values={"status":status.value,"note":note})
