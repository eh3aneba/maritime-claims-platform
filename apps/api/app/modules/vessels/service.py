from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.vessels.models import Vessel
from app.modules.vessels.schemas import VesselCreate


class DuplicateVesselError(ValueError):
    pass


def create_vessel(db: Session, *, organization_id: UUID, payload: VesselCreate) -> Vessel:
    if payload.imo_number:
        exists = db.scalar(
            select(Vessel.id).where(
                Vessel.organization_id == organization_id,
                Vessel.imo_number == payload.imo_number,
                Vessel.deleted_at.is_(None),
            )
        )
        if exists is not None:
            raise DuplicateVesselError("A vessel with this IMO number already exists in the organization")

    vessel = Vessel(
        organization_id=organization_id,
        name=payload.name.strip(),
        imo_number=payload.imo_number,
        vessel_type=payload.vessel_type.strip() if payload.vessel_type else None,
        flag=payload.flag.strip() if payload.flag else None,
        class_society=payload.class_society.strip() if payload.class_society else None,
        year_built=payload.year_built,
        deadweight=payload.deadweight,
        owner=payload.owner.strip() if payload.owner else None,
        manager=payload.manager.strip() if payload.manager else None,
    )
    db.add(vessel)
    db.flush()
    return vessel


def list_vessels(db: Session, *, organization_id: UUID, search: str | None = None) -> tuple[list[Vessel], int]:
    filters = [Vessel.organization_id == organization_id, Vessel.deleted_at.is_(None)]
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(or_(Vessel.name.ilike(pattern), Vessel.imo_number.ilike(pattern)))
    items = list(db.scalars(select(Vessel).where(*filters).order_by(Vessel.name.asc())))
    total = int(db.scalar(select(func.count(Vessel.id)).where(*filters)) or 0)
    return items, total
