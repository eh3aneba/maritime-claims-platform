from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.claims.models import Claim
    from app.modules.organizations.models import Organization


class Vessel(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "vessels"
    __table_args__ = (
        UniqueConstraint("organization_id", "imo_number", name="uq_vessels_org_imo"),
        Index("ix_vessels_org_name", "organization_id", "name"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    imo_number: Mapped[str | None] = mapped_column(String(7), nullable=True)
    vessel_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    flag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    class_society: Mapped[str | None] = mapped_column(String(150), nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_tonnage: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    deadweight: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manager: Mapped[str | None] = mapped_column(String(200), nullable=True)
    technical_manager: Mapped[str | None] = mapped_column(String(200), nullable=True)
    call_sign: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mmsi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    engine_maker: Mapped[str | None] = mapped_column(String(150), nullable=True)
    engine_model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    engine_power_kw: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="vessels")
    claims: Mapped[list["Claim"]] = relationship(back_populates="vessel")
