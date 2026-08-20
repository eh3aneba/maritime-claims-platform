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

## Sprint 11C — Bounded real-document private pilot

Goal: admit a small set of real non-restricted CE reports and engine logs without turning a successful benchmark into broad data-processing authorization.

Delivered application controls:

- append-only tenant-scoped pilot attempts anchored to current 11A activation and 11B promotion
- different organization-owner and data-owner approvers plus Admin-only final authorization
- fixed claim, document, user and provider-run caps with a maximum 30-day window
- document-level authorization/data-minimization attestations and Restricted-data prohibition
- queue-time checks for environment, pinned bundle, anchors, cohort, eligibility and quotas
- content-free provider-run ledger and mandatory review by a different human
- incident-triggered pause, Admin resolution/resume, immediate revocation and fail-closed completion
- dashboard, API, migration, audit events, tests, architecture document and ADR

The application does not grant the operational authorization automatically. The organization must provide real approval evidence and make the recorded decisions before any real document is eligible. Completion does not grant production-wide or Restricted-data authorization.

## Sprint 11D — Private-pilot outcome gate

Goal: turn a completed bounded pilot into measured, independently reviewed evidence without treating completion as production readiness.

Delivered application controls:

- append-only tenant-scoped assessments anchored to a completed Sprint 11C pilot
- one content-free usability observation for every immutable reviewed provider run
- fixed sample, workflow coverage, human action, usefulness, effort, latency, cost and incident thresholds
- separate CE Report and Engine Log scorecards plus first-half/second-half cost trend
- immutable SHA-256 scorecards and deterministic failure reasons
- different Product, Quality and Risk reviewers plus Admin-only final recommendation
- recommendation/extend/stop outcomes that always preserve `production_authorized: false`
- dashboard, API, migration, audit events, tests, architecture document and ADR

The application records an evidence-backed exit recommendation only. It does not enable Production, expand the cohort or admit Restricted documents.

## Sprint 11E — Next

Design the separately authorized limited-production evaluation control plane: deployment/environment isolation, tenant and document allowlists, rollout percentage, rollback SLOs, live quality/cost monitors, expiry and an independent authorization decision. Sprint 11D recommendation alone must remain insufficient.

## Deferred localization

Full English/Persian UI localization is deliberately deferred until the product reaches a stable post-evaluation stage. OCR continues to support English and Persian; this deferral concerns complete user-interface translation, locale formatting and RTL behavior.
