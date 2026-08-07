# ADR-023 — Equivalent evidence requires explicit human acceptance

## Status
Accepted — Sprint 5 Phase C

## Context
The MT ORION pilot showed that a document requirement can remain technically missing even when another reviewed source establishes the exact information required. For example, the Running Hours Record may expressly state the maker's recommended overhaul interval while the standalone Maker Recommendation document has not yet been supplied.

## Decision
- Rules may expose approved Claim Facts as candidate equivalent evidence for selected document requirements.
- Equivalent evidence never satisfies a requirement automatically.
- A human reviewer must explicitly accept the candidate and record a justification.
- The requirement records the approved Claim Fact, reviewer, timestamp, satisfaction basis and note.
- Accepted equivalent evidence satisfies readiness and may auto-complete the corresponding follow-up task.
- If the direct required document later arrives, direct evidence supersedes the equivalent-evidence satisfaction state while the previous action remains in the audit log.

## Consequences
Missing-document logic becomes evidence-aware rather than rigidly file-type-driven without weakening auditability. The first supported mappings cover maker interval, running hours and last-overhaul facts; additional mappings must be added deliberately rather than inferred by an LLM.
