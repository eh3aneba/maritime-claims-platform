# Maintenance & Workshop Intelligence — Sprint 4 Phase C

This phase adds structured AI extraction for Running Hours Records, PMS History and Workshop Reports.

## Safety boundaries
- Structured schemas only; no free-form causation conclusion.
- Every non-null extraction requires source segment + quote.
- Running-hours / maintenance scalar values enter `claim_facts` only after explicit human review.
- PMS rows, workshop findings and repair options remain repeatable reviewed evidence.
- Workshop suspected-cause statements remain `opinion` and never promote to confirmed cause.
- Deterministic Technical Review Matrix separates evidence for, counter-evidence, unknowns and follow-up.

## Processing jobs
- `ai_extract_running_hours`
- `ai_extract_pms_history`
- `ai_extract_workshop_report`

## Technical review endpoint
`GET /api/v1/claims/{claim_id}/technical-review`
