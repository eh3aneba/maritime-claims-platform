from __future__ import annotations

DOMAIN_CATALOG_VERSION = "16.1-A.1"

MACHINERY_COMPONENTS: tuple[dict[str, str], ...] = (
    {"code": "main_engine", "title": "Main Engine"},
    {"code": "turbocharger", "title": "Turbocharger"},
    {"code": "generator", "title": "Generator"},
    {"code": "propeller", "title": "Propeller"},
    {"code": "steering_gear", "title": "Steering Gear"},
    {"code": "boiler", "title": "Boiler"},
    {"code": "pump", "title": "Pump"},
)

_MACHINERY_COMPONENT_CODES = tuple(item["code"] for item in MACHINERY_COMPONENTS)

INCIDENT_DOMAINS: tuple[dict[str, object], ...] = (
    {
        "code": "machinery_failure",
        "title": "Machinery Failure",
        "description": "Human-confirmed machinery casualty context; not a causation or coverage determination.",
        "component_codes": list(_MACHINERY_COMPONENT_CODES),
        "contextual_rule_ids": ["TECH-001", "TECH-002", "TECH-003", "TECH-004", "TECH-005"],
    },
    {
        "code": "collision",
        "title": "Collision",
        "description": "Human-confirmed collision incident context; fault and liability remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": [],
    },
    {
        "code": "grounding",
        "title": "Grounding",
        "description": "Human-confirmed grounding incident context; causation and recoverability remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": [],
    },
    {
        "code": "fire",
        "title": "Fire",
        "description": "Human-confirmed fire incident context; origin, causation and coverage remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": [],
    },
    {
        "code": "cargo_damage",
        "title": "Cargo Damage",
        "description": "Human-confirmed cargo-damage context; liability and policy response remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": [],
    },
    {
        "code": "pollution",
        "title": "Pollution",
        "description": "Human-confirmed pollution incident context; legal responsibility and response remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": [],
    },
    {
        "code": "salvage",
        "title": "Salvage",
        "description": "Human-confirmed salvage context; entitlement and allocation remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": [],
    },
    {
        "code": "general_average",
        "title": "General Average",
        "description": "Human-confirmed General Average context; allowance and contribution remain separately governed.",
        "component_codes": [],
        "contextual_rule_ids": ["YAR-001", "YAR-002", "YAR-003", "YAR-004"],
    },
)

_INCIDENT_BY_CODE = {str(item["code"]): item for item in INCIDENT_DOMAINS}
_COMPONENT_CODES = {item["code"] for item in MACHINERY_COMPONENTS}


def domain_catalog_payload() -> dict:
    return {
        "catalog_version": DOMAIN_CATALOG_VERSION,
        "non_authoritative": True,
        "human_classification_required": True,
        "automatic_claim_decision": False,
        "incidents": [dict(item) for item in INCIDENT_DOMAINS],
        "machinery_components": [dict(item) for item in MACHINERY_COMPONENTS],
    }


def validate_domain_classification(
    incident_code: str,
    component_code: str | None,
    failure_mode: str | None,
) -> tuple[str, str | None, str | None]:
    normalized_incident = incident_code.strip().lower()
    normalized_component = component_code.strip().lower() if component_code else None
    normalized_failure_mode = failure_mode.strip() if failure_mode else None

    incident = _INCIDENT_BY_CODE.get(normalized_incident)
    if incident is None:
        raise ValueError("Unknown claim incident domain code")

    allowed_components = set(incident["component_codes"])
    if normalized_component is not None:
        if normalized_component not in _COMPONENT_CODES:
            raise ValueError("Unknown machinery component code")
        if normalized_component not in allowed_components:
            raise ValueError("Selected component is not compatible with the incident domain")
    if normalized_failure_mode is not None and normalized_component is None:
        raise ValueError("Failure mode requires a compatible machinery component")

    return normalized_incident, normalized_component, normalized_failure_mode
