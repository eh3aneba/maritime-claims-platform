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
