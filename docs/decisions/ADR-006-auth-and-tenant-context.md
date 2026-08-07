# ADR-006: Organization-aware authentication and backend-enforced tenant context

## Status
Accepted

## Decision
Login requires organization slug, email and password. JWTs carry user and organization context, but database membership remains authoritative. Every domain resource query is scoped by `organization_id` on the backend.

## Why
Emails are unique per organization, not globally. Explicit tenant context prevents ambiguous identity resolution and backend scoping prevents cross-tenant authorization bugs hidden by the UI.
