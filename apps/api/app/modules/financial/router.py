from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.financial.models import CostItem, FinancialFlag
from app.modules.financial.schemas import CostStatusUpdate, FinancialFlagResolve
from app.modules.financial.service import build_financial_review, resolve_financial_flag, update_cost_status

router=APIRouter(prefix="/claims/{claim_id}/financial-review",tags=["financial-review"])

@router.get("")
def get_financial_review(claim_id:UUID,current_user:CurrentUser,db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if claim is None: raise HTTPException(status_code=404,detail="Claim not found")
    result=build_financial_review(db,claim=claim,user_id=current_user.id);db.commit();return result

@router.post("/items/{item_id}/status")
def change_cost_status(claim_id:UUID,item_id:UUID,payload:CostStatusUpdate,current_user:CurrentUser,db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if claim is None: raise HTTPException(status_code=404,detail="Claim not found")
    item=db.get(CostItem,item_id)
    if item is None or item.claim_id!=claim.id or item.organization_id!=claim.organization_id: raise HTTPException(status_code=404,detail="Cost item not found")
    update_cost_status(db,claim=claim,item=item,status=payload.status,reason=payload.reason,user_id=current_user.id);db.commit();return {"id":str(item.id),"status":item.review_status.value}

@router.post("/flags/{flag_id}/resolve")
def resolve_flag(claim_id:UUID,flag_id:UUID,payload:FinancialFlagResolve,current_user:CurrentUser,db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if claim is None: raise HTTPException(status_code=404,detail="Claim not found")
    flag=db.get(FinancialFlag,flag_id)
    if flag is None or flag.claim_id!=claim.id or flag.organization_id!=claim.organization_id: raise HTTPException(status_code=404,detail="Financial flag not found")
    resolve_financial_flag(db,claim=claim,flag=flag,status=payload.status,note=payload.note,user_id=current_user.id);db.commit();return {"id":str(flag.id),"status":flag.status.value}
