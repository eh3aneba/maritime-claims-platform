# Claims API — Sprint 2 Phase E

## Endpoints

- `POST /api/v1/claims` — create a tenant-owned H&M machinery claim.
- `GET /api/v1/claims` — list/filter tenant claims with pagination.
- `GET /api/v1/claims/{id}` — retrieve a tenant claim.
- `PATCH /api/v1/claims/{id}` — edit core claim details.
- `POST /api/v1/claims/{id}/assign` — manager/admin handler assignment.
- `POST /api/v1/claims/{id}/status` — controlled state-machine transition.
- `POST /api/v1/claims/{id}/reserve` — temporary manager/admin reserve update with audit; reserve-history entity remains a later milestone.

## Security

Every lookup is scoped by authenticated `organization_id`. Cross-tenant objects return `404` rather than revealing their existence.

## Reference generation

Human-readable references follow `MCRI-HM-YYYY-NNNN`. PostgreSQL uses an atomic `INSERT .. ON CONFLICT DO UPDATE .. RETURNING` counter per tenant/year/claim type.

## Status control

Transitions are explicit. Terminal/high-authority destinations such as settlement, recovery, rejection, litigation and closure require a claims manager or administrator.
