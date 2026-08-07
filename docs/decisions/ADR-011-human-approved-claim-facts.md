# ADR-011: Separate AI candidates from human-approved claim facts

## Status
Accepted — Sprint 3 Phase C

## Decision
AI extraction candidates remain in `document_extractions`. Explicit human Approve/Edit actions may promote eligible factual values into a separate `claim_facts` table. Human review history is append-only in `ai_feedback`. AI output never writes directly to `claim_facts`.

Opinions/inferences are reviewable but non-promotable. Sensitive decision paths (including coverage, liability, root/confirmed causation, reserve, settlement, fraud and recoverability) are blocked from claim-fact promotion.

## Rationale
A marine claims system needs a clear boundary between machine-generated evidence candidates and the organization’s approved record. Keeping these layers separate preserves provenance, allows model outputs to be re-evaluated later, and prevents a fluent AI response from silently becoming an insurer/handler decision.

## Consequences
- More data structures than a simple overwrite model.
- Full human correction history can be audited and used for later evaluation/training.
- Approved facts can be consumed by chronology/rules engines without relying on raw AI output.
- Intake data and approved evidence facts may temporarily disagree; later reconciliation features must surface rather than hide those conflicts.
