# ADR-005: Audit records are immutable

Status: Accepted

## Decision
`audit_logs` has a creation timestamp but no update or soft-delete fields.

## Rationale
An audit trail loses evidentiary value if routine application behavior can alter or delete historical audit events. Corrections should create new events rather than mutate old ones.
