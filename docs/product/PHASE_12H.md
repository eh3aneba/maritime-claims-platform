# Phase 12H — AI Decision Log / AI Operations

## Goal
Give claims managers and admins one content-free operator workspace for governed AI activity across Sprint 11T document-processing Decision Logs and Phase 12G Claim Q&A synthesis runs.

## Delivered scope

### Unified events
- tenant-scoped read model over the two existing authoritative operational ledgers;
- deterministic newest-first ordering and bounded pagination;
- filters for workflow, claim/document, status, human review, provider/model, authorization, failure code, date and attention;
- content-free lineage drill-down for authorization/policy/eligibility/run/retrieval/input/output/answer/review hashes.

### Review queue
- pending Production Decision Log rows are surfaced as a first-class queue;
- review delegates to the existing Sprint 11T different-human workflow;
- approve/edit/reject retains existing metrics and immutable review hash semantics;
- Claim Q&A synthesis remains observability-only and transient synthesis wording is not persisted for retrospective review.

### Metrics and attention
- provider/review/synthesis counts;
- blocked/fallback and grounding-verification failures;
- authorization/policy/Restricted-data block counts;
- approve/edit/reject and unsupported/grounding metrics;
- tokens, observed provider cost and latency mean/P95 where source fields exist;
- recomputed attention signals rather than authoritative copied aggregates.

### Incident handoff
- explicit operator action only;
- reuses the existing Production-wide incident service for events with authorization lineage;
- no automatic incident declaration, authorization revocation or kill-switch action.

### Content-free export
- JSON and CSV from an explicit allowlist;
- audit record for generation with filter hash and row count;
- no raw claim/document text, prompt/question, source passage/quote, provider response, synthesis text or credentials.

### UI
- `/ai-operations` operator console;
- KPI/attention cards, filters, unified event table, pending review queue, lineage drill-down, claim deep link, incident handoff and export;
- explicit content-free/non-authoritative boundary warning;
- main application navigation entry.

## Safety / authority boundary
Phase 12H does not:
- authorize AI runtime execution;
- add providers/models/document classes;
- permit Restricted external processing;
- persist raw Q&A/model content in governance logs;
- update ClaimFact automatically;
- determine coverage, liability, causation, recoverability, reserve, settlement, payment or legal rights;
- autonomously declare incidents, revoke authorization or activate the kill switch.

## Validation target
Before merge, the exact PR head must pass the full backend regression suite, PostgreSQL migration/preflight chain, frontend TypeScript/build, dependency-lock consistency, Docker Compose validation, browser E2E and Supply Chain Security controls. Merge still requires fresh explicit user authorization.
