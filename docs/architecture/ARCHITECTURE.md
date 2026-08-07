# Architecture v1.0

## Style

Modular monolith.

## Runtime components

1. Next.js web application
2. FastAPI backend API
3. PostgreSQL database
4. File storage abstraction (local in development, S3-compatible later)

## Request flow

```text
Browser -> Next.js -> FastAPI -> PostgreSQL
                       |
                       -> File storage
```

Sprint 3 activates background document workers and controlled AI document intelligence on top of the secured claim/evidence foundation. OCR remains a separate pending capability for scanned evidence.

## Guardrails

- Backend-enforced multi-tenancy
- No direct frontend-to-database access
- No AI writes directly to approved claim facts
- UTC timestamps
- Decimal financial amounts
- Audit logging for sensitive changes
- Soft deletion for claims/documents where applicable

## Financial intelligence
Quotation and invoice AI outputs remain candidate evidence until human review. Reviewed commercial evidence is materialized into the claim cost schedule without promotion into scalar claim facts. Deterministic financial flags identify possible duplicates, pre-casualty invoice dates, betterment/ordinary-maintenance cues and quotation scope differences. These are review prompts only. Reserve changes are append-only in `reserve_history`.

## Initial Assessment Builder

Initial Assessments are versioned snapshots composed from authoritative and reviewed platform data. Each section stores its draft text, approved/edited text, review status, reviewer metadata, and a structured source manifest. Generation is blocked by Critical missing evidence unless a user explicitly creates a Preliminary assessment with an override reason. Overall approval requires section-by-section human review.
