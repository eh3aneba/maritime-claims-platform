# ADR-016: External document requests require explicit human confirmation

## Status
Accepted — Sprint 4 Phase B

## Decision
Creating a document-request draft or rule-driven task does **not** mean that the request was actually sent to an external party. A user must explicitly confirm that the correspondence was sent outside the platform before the related document requirement changes from `missing`/`rejected` to `requested`.

## Why
- Claims audit trails must distinguish drafted correspondence from issued correspondence.
- The MVP does not send email automatically.
- A rule or AI suggestion must not create a false external communication record.
- Human confirmation preserves accountability and prevents workflow state from overstating what happened.

## Lifecycle
`missing → draft/task created → human sends externally → requested → document received → received → task auto-completed`

`requested` remains unsatisfied for readiness purposes until evidence is actually received/accepted.
