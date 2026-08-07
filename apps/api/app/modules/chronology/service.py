from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.chronology.models import (
    ChronologyEvent,
    ChronologyMateriality,
    ConflictStatus,
    EventEvidence,
    EvidenceConflict,
)
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from app.modules.users.models import User

BUILD_VERSION = "1.0"
CLUSTER_TOLERANCE_MINUTES = 10
REVIEW_TOLERANCE_MINUTES = 30


@dataclass
class CandidateEvidence:
    extraction: DocumentExtraction
    document: Document
    value: Any


@dataclass
class EventCandidate:
    event_type: str
    title: str
    description: str | None
    occurred_on: date
    occurred_time: time
    timezone_label: str | None
    materiality: ChronologyMateriality
    source_priority: int
    evidence: list[CandidateEvidence] = field(default_factory=list)

    @property
    def timestamp(self) -> datetime:
        return datetime.combine(self.occurred_on, self.occurred_time)


@dataclass
class ConflictCandidate:
    conflict_type: str
    topic: str
    description: str
    value_a: Any
    value_b: Any
    materiality: ChronologyMateriality
    evidence_a: DocumentExtraction | None
    evidence_b: DocumentExtraction | None
    event_a: ChronologyEvent | None = None
    event_b: ChronologyEvent | None = None
    difference_minutes: Decimal | None = None


def _approved_value(extraction: DocumentExtraction) -> Any:
    if extraction.human_status not in {AIReviewStatus.APPROVED, AIReviewStatus.EDITED}:
        return None
    if extraction.human_status == AIReviewStatus.EDITED:
        return extraction.approved_value
    return extraction.approved_value if extraction.approved_value is not None else extraction.normalized_value if extraction.normalized_value is not None else extraction.raw_value


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        text = value.strip().upper().replace("UTC", "").strip()
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
    return None


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def _truthy(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in {"true", "yes", "1"}:
            return True
        if value.strip().lower() in {"false", "no", "0"}:
            return False
    return None


def _classify_action(text: str) -> tuple[str, str, ChronologyMateriality]:
    lowered = text.lower()
    if "shutdown" in lowered or "shut down" in lowered or "engine stopped" in lowered or "stopped engine" in lowered:
        return "shutdown", "Main engine shutdown", ChronologyMateriality.HIGH
    if "restart" in lowered or "re-start" in lowered or "resumed" in lowered:
        return "restart", "Main engine restart", ChronologyMateriality.HIGH
    if "reduce" in lowered and "load" in lowered:
        return "load_reduction", "Engine load reduced", ChronologyMateriality.MEDIUM
    if "isolat" in lowered:
        return "isolation", "Machinery isolated", ChronologyMateriality.HIGH
    if "tow" in lowered:
        return "towage", "Towage event", ChronologyMateriality.HIGH
    if "deviat" in lowered:
        return "deviation", "Vessel deviation", ChronologyMateriality.HIGH
    if "alarm" in lowered:
        return "alarm", "Machinery alarm", ChronologyMateriality.MEDIUM
    if "vibration" in lowered or "temperature" in lowered or "noise" in lowered:
        return "observation", "Abnormal machinery condition observed", ChronologyMateriality.MEDIUM
    return "action", "Operational action", ChronologyMateriality.LOW


def _event_signature(candidate: EventCandidate) -> str:
    evidence_ids = sorted(str(item.extraction.id) for item in candidate.evidence)
    payload = {
        "type": candidate.event_type,
        "date": candidate.occurred_on.isoformat(),
        "time": candidate.occurred_time.isoformat(),
        "evidence": evidence_ids,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _conflict_key(candidate: ConflictCandidate) -> str:
    payload = {
        "type": candidate.conflict_type,
        "topic": candidate.topic,
        "a": str(candidate.evidence_a.id) if candidate.evidence_a else None,
        "b": str(candidate.evidence_b.id) if candidate.evidence_b else None,
        "ea": str(candidate.event_a.id) if candidate.event_a else None,
        "eb": str(candidate.event_b.id) if candidate.event_b else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _load_reviewed_extractions(db: Session, *, claim_id: UUID, organization_id: UUID) -> list[tuple[DocumentExtraction, Document]]:
    return list(
        db.execute(
            select(DocumentExtraction, Document)
            .join(Document, Document.id == DocumentExtraction.document_id)
            .where(
                DocumentExtraction.claim_id == claim_id,
                DocumentExtraction.organization_id == organization_id,
                DocumentExtraction.human_status.in_([AIReviewStatus.APPROVED, AIReviewStatus.EDITED]),
                Document.deleted_at.is_(None),
            )
            .order_by(DocumentExtraction.created_at.asc())
        ).all()
    )


def _build_ce_candidates(rows: list[tuple[DocumentExtraction, Document]]) -> tuple[list[EventCandidate], dict[str, DocumentExtraction]]:
    by_doc: dict[UUID, dict[str, tuple[DocumentExtraction, Document]]] = {}
    for extraction, document in rows:
        if document.document_type != "chief_engineer_report":
            continue
        by_doc.setdefault(document.id, {})[extraction.field_path] = (extraction, document)

    candidates: list[EventCandidate] = []
    fact_index: dict[str, DocumentExtraction] = {}
    for fields in by_doc.values():
        date_pair = fields.get("incident.date")
        time_pair = fields.get("incident.time")
        if not date_pair or not time_pair:
            continue
        incident_date = _parse_date(_approved_value(date_pair[0]))
        incident_time = _parse_time(_approved_value(time_pair[0]))
        if not incident_date or not incident_time:
            continue
        tz_pair = fields.get("incident.timezone")
        timezone_label = _string(_approved_value(tz_pair[0])) if tz_pair else None

        for path, pair in fields.items():
            extraction, document = pair
            value = _approved_value(extraction)
            fact_index[path] = extraction
            if value is None:
                continue
            if path == "incident.first_observation":
                text = _string(value)
                if text:
                    kind, title, materiality = _classify_action(text)
                    if kind == "action":
                        kind, title, materiality = "observation", "First abnormality observed", ChronologyMateriality.MEDIUM
                    evidence = [CandidateEvidence(date_pair[0], date_pair[1], _approved_value(date_pair[0])), CandidateEvidence(time_pair[0], time_pair[1], _approved_value(time_pair[0])), CandidateEvidence(extraction, document, value)]
                    if tz_pair:
                        evidence.append(CandidateEvidence(tz_pair[0], tz_pair[1], _approved_value(tz_pair[0])))
                    candidates.append(EventCandidate(kind, title, text, incident_date, incident_time, timezone_label, materiality, 70, evidence))
            elif path.startswith("immediate_actions["):
                text = _string(value)
                if text:
                    kind, title, materiality = _classify_action(text)
                    candidates.append(EventCandidate(kind, title, text, incident_date, incident_time, timezone_label, materiality, 70, [CandidateEvidence(date_pair[0], date_pair[1], _approved_value(date_pair[0])), CandidateEvidence(time_pair[0], time_pair[1], _approved_value(time_pair[0])), CandidateEvidence(extraction, document, value)]))
            elif path == "operational_impact.engine_stopped" and _truthy(value) is True:
                candidates.append(EventCandidate("shutdown", "Main engine shutdown", "Chief Engineer Report records that the engine stopped.", incident_date, incident_time, timezone_label, ChronologyMateriality.HIGH, 70, [CandidateEvidence(date_pair[0], date_pair[1], _approved_value(date_pair[0])), CandidateEvidence(time_pair[0], time_pair[1], _approved_value(time_pair[0])), CandidateEvidence(extraction, document, value)]))
            elif path == "operational_impact.load_reduced" and _truthy(value) is True:
                candidates.append(EventCandidate("load_reduction", "Engine load reduced", "Chief Engineer Report records reduced engine load.", incident_date, incident_time, timezone_label, ChronologyMateriality.MEDIUM, 70, [CandidateEvidence(date_pair[0], date_pair[1], _approved_value(date_pair[0])), CandidateEvidence(time_pair[0], time_pair[1], _approved_value(time_pair[0])), CandidateEvidence(extraction, document, value)]))
            elif path == "operational_impact.deviation" and _truthy(value) is True:
                candidates.append(EventCandidate("deviation", "Vessel deviation", "Chief Engineer Report records a deviation.", incident_date, incident_time, timezone_label, ChronologyMateriality.HIGH, 70, [CandidateEvidence(date_pair[0], date_pair[1], _approved_value(date_pair[0])), CandidateEvidence(time_pair[0], time_pair[1], _approved_value(time_pair[0])), CandidateEvidence(extraction, document, value)]))
            elif path == "operational_impact.towage" and _truthy(value) is True:
                candidates.append(EventCandidate("towage", "Towage event", "Chief Engineer Report records towage.", incident_date, incident_time, timezone_label, ChronologyMateriality.HIGH, 70, [CandidateEvidence(date_pair[0], date_pair[1], _approved_value(date_pair[0])), CandidateEvidence(time_pair[0], time_pair[1], _approved_value(time_pair[0])), CandidateEvidence(extraction, document, value)]))
    return candidates, fact_index


_ENGINE_EVENT_RE = re.compile(r"^engine_log\.events\[(\d+)\]\.(.+)$")


def _build_engine_candidates(rows: list[tuple[DocumentExtraction, Document]]) -> tuple[list[EventCandidate], dict[str, DocumentExtraction]]:
    grouped: dict[tuple[UUID, int], dict[str, tuple[DocumentExtraction, Document]]] = {}
    fact_index: dict[str, DocumentExtraction] = {}
    for extraction, document in rows:
        if document.document_type != "engine_log":
            continue
        match = _ENGINE_EVENT_RE.match(extraction.field_path)
        if not match:
            continue
        index, field_name = int(match.group(1)), match.group(2)
        grouped.setdefault((document.id, index), {})[field_name] = (extraction, document)

    candidates: list[EventCandidate] = []
    for (_, index), fields in grouped.items():
        if "date" not in fields or "time" not in fields:
            continue
        event_date = _parse_date(_approved_value(fields["date"][0]))
        event_time = _parse_time(_approved_value(fields["time"][0]))
        if not event_date or not event_time:
            continue
        timezone_label = _string(_approved_value(fields["timezone"][0])) if "timezone" in fields else None
        values = {name: _approved_value(pair[0]) for name, pair in fields.items()}
        for name, pair in fields.items():
            fact_index[f"engine_log.events[{index}].{name}"] = pair[0]

        event_type = None
        title = None
        materiality = ChronologyMateriality.LOW
        description_parts: list[str] = []
        if _truthy(values.get("shutdown")) is True:
            event_type, title, materiality = "shutdown", "Main engine shutdown", ChronologyMateriality.HIGH
        elif _truthy(values.get("restart")) is True:
            event_type, title, materiality = "restart", "Main engine restart", ChronologyMateriality.HIGH
        elif _string(values.get("alarm")):
            event_type, title, materiality = "alarm", "Machinery alarm", ChronologyMateriality.MEDIUM
        elif _string(values.get("action")):
            event_type, title, materiality = _classify_action(_string(values.get("action")) or "")
        elif _string(values.get("remarks")):
            event_type, title, materiality = _classify_action(_string(values.get("remarks")) or "")
        elif _string(values.get("event_type")):
            event_type = (_string(values.get("event_type")) or "log_event").lower().replace(" ", "_")
            title = "Engine log event"
        else:
            event_type, title = "log_event", "Engine log event"

        for label, key in (("Alarm", "alarm"), ("Action", "action"), ("Remarks", "remarks")):
            text = _string(values.get(key))
            if text:
                description_parts.append(f"{label}: {text}")
        for label, key in (("RPM", "rpm"), ("Load", "engine_load"), ("TC speed", "turbocharger_speed"), ("Exhaust temp", "exhaust_temperature"), ("Lube oil pressure", "lube_oil_pressure")):
            value = values.get(key)
            if value is not None:
                description_parts.append(f"{label}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}")

        evidence = [CandidateEvidence(pair[0], pair[1], _approved_value(pair[0])) for pair in fields.values()]
        candidates.append(EventCandidate(event_type, title or "Engine log event", "; ".join(description_parts) or None, event_date, event_time, timezone_label, materiality, 100, evidence))
    return candidates, fact_index


def _cluster_candidates(candidates: list[EventCandidate]) -> list[EventCandidate]:
    clusters: list[list[EventCandidate]] = []
    for candidate in sorted(candidates, key=lambda c: (c.timestamp, c.event_type, -c.source_priority)):
        matched = None
        for cluster in clusters:
            representative = max(cluster, key=lambda c: c.source_priority)
            if representative.event_type != candidate.event_type or representative.occurred_on != candidate.occurred_on:
                continue
            if representative.timezone_label and candidate.timezone_label and representative.timezone_label != candidate.timezone_label:
                continue
            diff = abs((representative.timestamp - candidate.timestamp).total_seconds()) / 60
            if diff <= CLUSTER_TOLERANCE_MINUTES:
                matched = cluster
                break
        if matched is None:
            clusters.append([candidate])
        else:
            matched.append(candidate)

    result: list[EventCandidate] = []
    for cluster in clusters:
        primary = max(cluster, key=lambda c: (c.source_priority, -c.timestamp.timestamp()))
        evidence_by_id: dict[UUID, CandidateEvidence] = {}
        descriptions: list[str] = []
        materiality = primary.materiality
        # Keep the highest-priority source first so EventEvidence can label it as primary.
        ordered_cluster = [primary] + [item for item in cluster if item is not primary]
        for item in ordered_cluster:
            if item.description and item.description not in descriptions:
                descriptions.append(item.description)
            if list(ChronologyMateriality).index(item.materiality) > list(ChronologyMateriality).index(materiality):
                materiality = item.materiality
            for evidence in item.evidence:
                evidence_by_id.setdefault(evidence.extraction.id, evidence)
        result.append(EventCandidate(primary.event_type, primary.title, " | ".join(descriptions) or None, primary.occurred_on, primary.occurred_time, primary.timezone_label, materiality, primary.source_priority, list(evidence_by_id.values())))
    return result


def _upsert_events(db: Session, *, claim: Claim, candidates: list[EventCandidate]) -> list[ChronologyEvent]:
    db.execute(update(ChronologyEvent).where(ChronologyEvent.claim_id == claim.id, ChronologyEvent.organization_id == claim.organization_id).values(is_active=False))
    active: list[ChronologyEvent] = []
    for candidate in candidates:
        signature = _event_signature(candidate)
        event = db.scalar(select(ChronologyEvent).where(ChronologyEvent.organization_id == claim.organization_id, ChronologyEvent.claim_id == claim.id, ChronologyEvent.source_signature == signature))
        if event is None:
            event = ChronologyEvent(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                event_type=candidate.event_type,
                title=candidate.title,
                description=candidate.description,
                occurred_on=candidate.occurred_on,
                occurred_time=candidate.occurred_time,
                timezone_label=candidate.timezone_label,
                materiality=candidate.materiality,
                source_signature=signature,
                build_version=BUILD_VERSION,
                is_active=True,
            )
            db.add(event)
            db.flush()
        else:
            event.event_type = candidate.event_type
            event.title = candidate.title
            event.description = candidate.description
            event.occurred_on = candidate.occurred_on
            event.occurred_time = candidate.occurred_time
            event.timezone_label = candidate.timezone_label
            event.materiality = candidate.materiality
            event.build_version = BUILD_VERSION
            event.is_active = True
            db.flush()
        db.execute(delete(EventEvidence).where(EventEvidence.event_id == event.id))
        for idx, evidence in enumerate(candidate.evidence):
            db.add(EventEvidence(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                event_id=event.id,
                extraction_id=evidence.extraction.id,
                document_id=evidence.document.id,
                source_segment_id=evidence.extraction.source_segment_id,
                evidence_role="primary" if idx == 0 else "supporting",
            ))
        active.append(event)
    db.flush()
    return active


def _representative_extraction(db: Session, event_id: UUID, suffix: str | None = None) -> DocumentExtraction | None:
    query = select(DocumentExtraction).join(EventEvidence, EventEvidence.extraction_id == DocumentExtraction.id).where(EventEvidence.event_id == event_id)
    if suffix:
        query = query.where(DocumentExtraction.field_path.endswith(suffix))
    return db.scalar(query.order_by(DocumentExtraction.created_at.asc()))


def _time_conflicts(db: Session, events: list[ChronologyEvent]) -> list[ConflictCandidate]:
    unique_types = {"shutdown", "restart", "load_reduction", "towage", "deviation", "isolation"}
    conflicts: list[ConflictCandidate] = []
    ordered = sorted(events, key=lambda event: (event.event_type, event.occurred_on, event.occurred_time))
    for idx, event_a in enumerate(ordered):
        if event_a.event_type not in unique_types:
            continue
        for event_b in ordered[idx + 1:]:
            if event_b.event_type != event_a.event_type:
                if event_b.event_type > event_a.event_type:
                    break
                continue
            if event_a.occurred_on != event_b.occurred_on:
                materiality = ChronologyMateriality.CRITICAL
                diff_minutes = None
            else:
                diff = abs((datetime.combine(event_a.occurred_on, event_a.occurred_time) - datetime.combine(event_b.occurred_on, event_b.occurred_time)).total_seconds()) / 60
                if diff <= CLUSTER_TOLERANCE_MINUTES:
                    continue
                diff_minutes = Decimal(str(round(diff, 2)))
                materiality = ChronologyMateriality.MEDIUM if diff <= REVIEW_TOLERANCE_MINUTES else ChronologyMateriality.HIGH
            a_ex = _representative_extraction(db, event_a.id, ".time") or _representative_extraction(db, event_a.id)
            b_ex = _representative_extraction(db, event_b.id, ".time") or _representative_extraction(db, event_b.id)
            conflicts.append(ConflictCandidate(
                conflict_type="timestamp",
                topic=f"{event_a.event_type} time",
                description=(f"Reviewed evidence records materially different times for the same {event_a.event_type.replace('_', ' ')} event." if diff_minutes is not None else f"Reviewed evidence records different dates for the same {event_a.event_type.replace('_', ' ')} event."),
                value_a={"date": event_a.occurred_on.isoformat(), "time": event_a.occurred_time.isoformat(), "timezone": event_a.timezone_label},
                value_b={"date": event_b.occurred_on.isoformat(), "time": event_b.occurred_time.isoformat(), "timezone": event_b.timezone_label},
                materiality=materiality,
                evidence_a=a_ex,
                evidence_b=b_ex,
                event_a=event_a,
                event_b=event_b,
                difference_minutes=diff_minutes,
            ))
    return conflicts


def _boolean_conflicts(rows: list[tuple[DocumentExtraction, Document]], events: list[ChronologyEvent], db: Session) -> list[ConflictCandidate]:
    ce_flags: dict[str, DocumentExtraction] = {}
    for extraction, document in rows:
        if document.document_type == "chief_engineer_report" and extraction.field_path in {"operational_impact.engine_stopped", "operational_impact.load_reduced"}:
            ce_flags[extraction.field_path] = extraction
    conflicts: list[ConflictCandidate] = []
    mappings = [
        ("operational_impact.engine_stopped", "shutdown", "engine stopped"),
        ("operational_impact.load_reduced", "load_reduction", "engine load reduced"),
    ]
    for ce_path, event_type, topic in mappings:
        extraction = ce_flags.get(ce_path)
        if extraction is None or _truthy(_approved_value(extraction)) is not False:
            continue
        matching = [event for event in events if event.event_type == event_type]
        if not matching:
            continue
        event = matching[0]
        other = _representative_extraction(db, event.id)
        conflicts.append(ConflictCandidate(
            conflict_type="content",
            topic=topic,
            description=f"Chief Engineer Report records '{topic}' as false while reviewed operational evidence indicates the event occurred.",
            value_a=False,
            value_b=True,
            materiality=ChronologyMateriality.HIGH,
            evidence_a=extraction,
            evidence_b=other,
            event_b=event,
        ))
    return conflicts


def _upsert_conflicts(db: Session, *, claim: Claim, conflicts: list[ConflictCandidate]) -> list[EvidenceConflict]:
    db.execute(update(EvidenceConflict).where(EvidenceConflict.claim_id == claim.id, EvidenceConflict.organization_id == claim.organization_id).values(is_active=False))
    active: list[EvidenceConflict] = []
    for candidate in conflicts:
        key = _conflict_key(candidate)
        conflict = db.scalar(select(EvidenceConflict).where(EvidenceConflict.organization_id == claim.organization_id, EvidenceConflict.claim_id == claim.id, EvidenceConflict.conflict_key == key))
        if conflict is None:
            conflict = EvidenceConflict(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                event_a_id=candidate.event_a.id if candidate.event_a else None,
                event_b_id=candidate.event_b.id if candidate.event_b else None,
                evidence_a_extraction_id=candidate.evidence_a.id if candidate.evidence_a else None,
                evidence_b_extraction_id=candidate.evidence_b.id if candidate.evidence_b else None,
                conflict_key=key,
                conflict_type=candidate.conflict_type,
                topic=candidate.topic,
                description=candidate.description,
                value_a=candidate.value_a,
                value_b=candidate.value_b,
                difference_minutes=candidate.difference_minutes,
                materiality=candidate.materiality,
                status=ConflictStatus.OPEN,
                is_active=True,
            )
            db.add(conflict)
        else:
            conflict.event_a_id = candidate.event_a.id if candidate.event_a else None
            conflict.event_b_id = candidate.event_b.id if candidate.event_b else None
            conflict.evidence_a_extraction_id = candidate.evidence_a.id if candidate.evidence_a else None
            conflict.evidence_b_extraction_id = candidate.evidence_b.id if candidate.evidence_b else None
            conflict.description = candidate.description
            conflict.value_a = candidate.value_a
            conflict.value_b = candidate.value_b
            conflict.difference_minutes = candidate.difference_minutes
            conflict.materiality = candidate.materiality
            conflict.is_active = True
        active.append(conflict)
    db.flush()
    return active


def build_chronology(db: Session, *, claim: Claim, user: User) -> tuple[list[ChronologyEvent], list[EvidenceConflict]]:
    reviewed = _load_reviewed_extractions(db, claim_id=claim.id, organization_id=claim.organization_id)
    ce_candidates, _ = _build_ce_candidates(reviewed)
    engine_candidates, _ = _build_engine_candidates(reviewed)
    clustered = _cluster_candidates(ce_candidates + engine_candidates)
    events = _upsert_events(db, claim=claim, candidates=clustered)
    conflicts = _time_conflicts(db, events) + _boolean_conflicts(reviewed, events, db)
    active_conflicts = _upsert_conflicts(db, claim=claim, conflicts=conflicts)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="BUILD_CLAIM_CHRONOLOGY",
        entity_type="claim",
        entity_id=claim.id,
        new_values={"event_count": len(events), "conflict_count": len(active_conflicts), "build_version": BUILD_VERSION},
        details="Chronology rebuilt from human-reviewed evidence; no source was adjudicated as true by the rules engine.",
    )
    db.commit()
    return events, active_conflicts


def resolve_conflict(db: Session, *, conflict: EvidenceConflict, user: User, status: ConflictStatus, note: str) -> EvidenceConflict:
    old = {"status": conflict.status.value, "resolution_note": conflict.resolution_note}
    conflict.status = status
    conflict.resolution_note = note.strip()
    conflict.resolved_by_id = user.id
    conflict.resolved_at = datetime.now(UTC)
    write_audit_log(
        db,
        organization_id=conflict.organization_id,
        user_id=user.id,
        action="RESOLVE_EVIDENCE_CONFLICT",
        entity_type="evidence_conflict",
        entity_id=conflict.id,
        old_values=old,
        new_values={"status": status.value, "resolution_note": conflict.resolution_note},
    )
    db.commit()
    db.refresh(conflict)
    return conflict
