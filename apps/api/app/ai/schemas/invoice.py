from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.ai.schemas.quotation import EvidenceRef, SourcedBoolean, SourcedString

class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: Literal["invoice", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)

class InvoiceLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: SourcedString
    quantity: SourcedString
    unit: SourcedString
    unit_price: SourcedString
    amount: SourcedString
    category_candidate: SourcedString
    potential_betterment_cue: SourcedBoolean
    potential_ordinary_maintenance_cue: SourcedBoolean

    @model_validator(mode="after")
    def meaningful(self):
        if not any(x.value is not None for x in [self.description, self.quantity, self.unit_price, self.amount]):
            raise ValueError("Invoice line item must contain supported commercial evidence.")
        return self

class InvoiceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    supplier: SourcedString
    invoice_number: SourcedString
    invoice_date: SourcedString
    purchase_order: SourcedString
    related_quotation_number: SourcedString
    currency: SourcedString
    subtotal: SourcedString
    tax: SourcedString
    discount: SourcedString
    total: SourcedString
    payment_terms: SourcedString
    line_items: list[InvoiceLineItem]
