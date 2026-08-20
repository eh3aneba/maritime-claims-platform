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

## Sprint 11B — Next

Build a versioned evaluation harness and promotion gate for representative synthetic/de-identified CE reports, engine logs, maintenance records and financial documents. Measure field-level accuracy, unsupported claims, source-link validity, prompt-injection resistance, tenant isolation, latency, tokens, cost and human-review overrides. Every threshold must be pinned to the activation’s model/prompt/schema bundle and a failure must block promotion.

## Deferred localization

Full English/Persian UI localization is deliberately deferred until the product reaches a stable post-evaluation stage. OCR continues to support English and Persian; this deferral concerns complete user-interface translation, locale formatting and RTL behavior.

