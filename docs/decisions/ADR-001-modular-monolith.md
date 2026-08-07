# ADR-001: Use a modular monolith for the MVP

Status: Accepted

## Decision
Use one FastAPI backend organized by business modules rather than microservices.

## Rationale
- Solo-founder maintainability
- Simpler deployment and debugging
- Easier transactions and audit consistency
- No demonstrated scaling need for distributed services yet
