from __future__ import annotations

from app.modules.rules import service_core as _core

# Preserve the existing rules-service public/private surface while keeping the
# Phase 12B integration wrapper small and reviewable. The implementation copied
# to service_core.py is byte-identical to the previously validated service.py.
for _name in dir(_core):
    if not _name.startswith("__") and _name != "evaluate_claim_rules":
        globals()[_name] = getattr(_core, _name)


def evaluate_claim_rules(db, *, claim, user, trigger: str = "manual"):
    """Evaluate core claim rules and attach the composed Marine Rules Engine.

    The marine layer remains non-authoritative. It enriches the same immutable
    RuleEvaluationRun, uses only controlled claim evidence and reviewed wording,
    and materializes evidence-rich ClaimIssue records for downstream Claims Intelligence.
    """
    run = _core.evaluate_claim_rules(db, claim=claim, user=user, trigger=trigger)
    from app.modules.rules.marine_engine_service import attach_marine_rules_to_run

    return attach_marine_rules_to_run(db, claim=claim, user=user, run=run)
