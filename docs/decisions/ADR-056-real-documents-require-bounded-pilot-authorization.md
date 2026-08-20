# ADR-056: Real documents require a separately bounded pilot authorization

## Status

Accepted for Sprint 11C.

## Decision

Passing synthetic/de-identified evaluation does not authorize real claim data. Real non-restricted Chief Engineer Reports and Engine Logs may reach the external provider only inside an append-only, tenant-scoped private-pilot attempt anchored to the active Sprint 11A activation and Sprint 11B promotion.

The pilot freezes document classes, claim/document/user/run caps and an expiry of no more than 30 days. Separate organization-owner and data-owner approvals plus an Admin decision are mandatory. Every document also requires an explicit authorization/data-minimization attestation, and every provider run requires a content-free ledger entry and a different human reviewer.

Incidents pause new runs immediately. Revocation is a kill switch. Completion cannot be recorded until all runs are human-reviewed and all incidents are resolved.

## Consequences

- Configuration, activation and benchmark promotion remain insufficient to process real documents.
- Restricted documents, broad production use and autonomous claim decisions remain prohibited.
- The control ledger holds hashes and bounded references, not claim content or provider responses.
- Cohort or model/prompt/schema expansion requires a fresh authorization/evaluation path.
- Pilot completion supplies evidence for, but never automatically grants, a later production-AI decision.

