from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_index: int | None
    quote: str | None

class SourcedString(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | None
    confidence: float = Field(ge=0, le=1)
    source: EvidenceRef

class SourcedBoolean(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool | None
    confidence: float = Field(ge=0, le=1)
    source: EvidenceRef

class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: Literal["quotation", "other", "unknown"]
    confidence: float = Field(ge=0, le=1)

class QuotationLineItem(BaseModel):
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
            raise ValueError("Quotation line item must contain supported commercial evidence.")
        return self

class QuotationExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Classification
    supplier: SourcedString
    quotation_number: SourcedString
    quotation_date: SourcedString
    currency: SourcedString
    subtotal: SourcedString
    tax: SourcedString
    freight: SourcedString
    total: SourcedString
    validity: SourcedString
    lead_time: SourcedString
    repair_duration: SourcedString
    scope_summary: SourcedString
    exclusions: list[SourcedString]
    line_items: list[QuotationLineItem]
