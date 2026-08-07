# ADR-004: Carry organization_id on tenant-owned tables

Status: Accepted

## Decision
Every tenant-owned business table carries an explicit `organization_id`, even when tenant ownership could theoretically be inferred through another relation.

## Rationale
- Makes authorization queries explicit and easier to review.
- Reduces risk of cross-tenant joins leaking records.
- Enables organization-scoped indexes.
- Supports future row-level security if required.

Backend authorization remains mandatory; the column alone is not an access-control mechanism.
