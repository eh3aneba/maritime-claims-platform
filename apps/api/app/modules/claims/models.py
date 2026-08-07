import enum
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_values

if TYPE_CHECKING:
    from app.modules.documents.models import Document
    from app.modules.organizations.models import Organization
    from app.modules.users.models import User
    from app.modules.vessels.models import Vessel


class ClaimType(str, enum.Enum):
    HULL_MACHINERY = "hull_machinery"


class ClaimSubtype(str, enum.Enum):
    MACHINERY_DAMAGE = "machinery_damage"


class ClaimStatus(str, enum.Enum):
    NEW = "new"
    TRIAGE = "triage"
    AWAITING_DOCUMENTS = "awaiting_documents"
    INVESTIGATION = "investigation"
    TECHNICAL_REVIEW = "technical_review"
    FINANCIAL_REVIEW = "financial_review"
    COVERAGE_REVIEW = "coverage_review"
    NEGOTIATION = "negotiation"
    SETTLEMENT = "settlement"
    RECOVERY = "recovery"
    CLOSED = "closed"
    ON_HOLD = "on_hold"
    LITIGATION = "litigation"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ClaimPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Claim(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint("organization_id", "claim_reference", name="uq_claims_org_reference"),
        CheckConstraint("char_length(currency) = 3", name="ck_claims_currency_len"),
        Index("ix_claims_org_status", "organization_id", "status"),
        Index("ix_claims_org_incident_date", "organization_id", "incident_date"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vessel_id: Mapped[UUID] = mapped_column(
        ForeignKey("vessels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    handler_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    claim_reference: Mapped[str] = mapped_column(String(50), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claim_type: Mapped[ClaimType] = mapped_column(
        Enum(ClaimType, name="claim_type", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ClaimType.HULL_MACHINERY,
        server_default=ClaimType.HULL_MACHINERY.value,
    )
    claim_subtype: Mapped[ClaimSubtype] = mapped_column(
        Enum(ClaimSubtype, name="claim_subtype", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ClaimSubtype.MACHINERY_DAMAGE,
        server_default=ClaimSubtype.MACHINERY_DAMAGE.value,
    )
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ClaimStatus.NEW,
        server_default=ClaimStatus.NEW.value,
    )
    priority: Mapped[ClaimPriority] = mapped_column(
        Enum(ClaimPriority, name="claim_priority", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=ClaimPriority.MEDIUM,
        server_default=ClaimPriority.MEDIUM.value,
    )

    incident_date: Mapped[date] = mapped_column(Date, nullable=False)
    notification_date: Mapped[date] = mapped_column(Date, nullable=False)
    incident_description: Mapped[str] = mapped_column(Text, nullable=False)

    estimated_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_reserve: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")

    organization: Mapped["Organization"] = relationship(back_populates="claims")
    vessel: Mapped["Vessel"] = relationship(back_populates="claims")
    handler: Mapped["User | None"] = relationship(
        back_populates="assigned_claims", foreign_keys=[handler_id]
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="claim")
