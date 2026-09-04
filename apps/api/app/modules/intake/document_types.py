from __future__ import annotations

INTAKE_DOCUMENT_TYPES: tuple[str, ...] = (
    "claim_notification",
    "chief_engineer_report",
    "survey_report",
    "engine_log",
    "running_hours_record",
    "pms_record",
    "workshop_report",
    "quotation",
    "invoice",
    "class_report",
    "repair_report",
    "correspondence",
    "other",
)

INTAKE_DOCUMENT_TYPE_SET = frozenset(INTAKE_DOCUMENT_TYPES)
DEFAULT_INTAKE_DOCUMENT_TYPE = "claim_notification"


def is_intake_document_type(value: str | None) -> bool:
    return bool(value and value in INTAKE_DOCUMENT_TYPE_SET)
