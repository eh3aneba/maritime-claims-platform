# Human AI Review Architecture

Sprint 3 Phase C completes the first controlled `AI -> human -> approved record` workflow.

## Core boundary

AI-generated `document_extractions` remain candidate data. They cannot update `claim_facts` directly.

Only an authenticated human review action may:
- approve an extracted value,
- edit/correct it,
- reject it.

Every action is recorded in append-only `ai_feedback` and in the general `audit_logs` trail.

## Authoritative claim facts

`claim_facts` stores the current human-approved structured fact for a claim/field path.

Important properties:
- tenant-scoped,
- one current value per claim + field path,
- source extraction/document/segment retained,
- reviewer and approval timestamp retained,
- version increments when a later human-approved extraction replaces the current fact.

This layer is intentionally separate from raw AI output and from initial claim-intake fields. Phase C does not silently overwrite the Claim or Vessel records when evidence differs from intake data.

## Facts versus opinions

Human review confirms extraction quality, not truth of causation or coverage.

- `fact` candidates may be promoted to `claim_facts` after human approval.
- `opinion` and `inference` candidates may be approved as correctly extracted evidence, but are never promoted as claim facts.
- sensitive paths such as coverage, liability, confirmed/root cause, reserve, settlement, fraud and recoverability are blocked from claim-fact promotion even if a future schema labels them incorrectly.

## Source controls

Individual approval/edit is allowed for an unverified source citation only when the reviewer records a reason documenting their manual verification.

Bulk approval is stricter. It requires:
- pending status,
- semantic kind `fact`,
- a whitelisted low-risk metadata field,
- confidence >= 0.90,
- verified source quote,
- a persisted source segment.

Incident time, operational impact and causation-related material are not bulk approvable.

## Re-review and history

Review actions are reversible through a later explicit human action. The current extraction status/value changes, but previous review events remain in `ai_feedback`.

If an extraction that currently supplies an authoritative `claim_fact` is later rejected, that current fact is removed. If a later extraction already replaced it as the authoritative source, rejecting the older extraction does not remove the newer fact.

## API

- `GET /api/v1/ai-review`
- `GET /api/v1/ai-review/{extraction_id}`
- `GET /api/v1/ai-review/{extraction_id}/source`
- `POST /api/v1/ai-review/{extraction_id}`
- `POST /api/v1/ai-review/bulk/approve`
- `GET /api/v1/claims/{claim_id}/facts`

All endpoints are backend tenant-scoped.
