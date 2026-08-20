# Sprint 11 — Controlled External AI Evaluation

## Sprint 11A — Provider activation and evaluation gate

Goal: make synthetic/de-identified staging evaluation possible without allowing a configured key to silently become data-processing authorization.

Delivered control-plane capabilities:

- append-only tenant-scoped OpenAI staging activation attempts
- pinned model, prompt bundle, schema bundle and document allowlist
- declared input/output, rate, token and monthly spend boundaries
- bounded references for secret, spend, data-processing and kill-switch evidence
- three independent Security/Privacy/Product approvals plus Admin final decision
- canonical SHA-256 decision snapshot and audit events
- per-document synthetic/de-identified eligibility attestations
- queue-time enforcement on every supported external OpenAI extraction path
- explicit activation and document revoke controls
- dashboard for the activation and eligibility ledgers

Non-goals remain explicit: no key storage, provider mutation, production activation, restricted or real-claim authorization, autonomous claim decision or human-review bypass.

## Sprint 11B — Quality, safety and cost promotion gate

Goal: prevent a scoped provider activation from being mistaken for evidence that the pinned AI bundle is safe or useful.

Delivered application controls:

- append-only evaluation suites anchored to an active Sprint 11A activation
- server-owned `quality_safety_cost_v1` threshold profile
- content-free, SHA-256 case-result ledger
- deterministic precision, recall, unsupported-claim, quote-validity, override, latency and observed-cost metrics
- mandatory CE report and engine-log representation
- mandatory prompt-injection, malformed-input, cross-tenant and restricted-data cases
- immutable failure reasons; failed or incomplete attempts cannot be reviewed into a pass
- independent Quality/Risk reviews plus Admin-only Promote/Hold
- expiring staging promotion and explicit revocation
- tenant-safe dashboard, API, migration, tests, audit events and ADR

The application does not run the external benchmark or calculate provider billing. Operators run the controlled synthetic/de-identified corpus, retain it in the approved artifact system and record only aggregate observations plus bounded references.

## Sprint 11C — Next

Create the separately authorized bounded real-document private pilot. It must require organization/data-owner approval, a small non-restricted cohort, current 11A activation and 11B promotion, mandatory human review, monitoring and immediate rollback. No real claim document is authorized by Sprints 11A or 11B.

## Deferred localization

Full English/Persian UI localization is deliberately deferred until the product reaches a stable post-evaluation stage. OCR continues to support English and Persian; this deferral concerns complete user-interface translation, locale formatting and RTL behavior.
