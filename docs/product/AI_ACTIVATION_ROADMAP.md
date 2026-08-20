# External AI Activation Roadmap

## Current capability

The product already has a provider-neutral gateway, an OpenAI adapter using the Responses API and strict Structured Outputs, source-linked extraction candidates, quote verification, confidence fields, append-only feedback and mandatory Approve/Edit/Reject human review. AI candidates never directly update authoritative claim facts. The external provider remains disabled by default, and restricted documents remain blocked unless separately enabled.

This means direct AI can be exercised today in a developer environment with synthetic documents after explicit local configuration. That is a technical exercise, not authorization for production or real claim data.

## Sprint 11A — Provider Activation & Evaluation Gate

- separate OpenAI staging and production projects and credentials
- secret-manager/environment-only key handling; no database, source or log storage
- explicit document-classification allowlist and restricted-data prohibition by default
- pinned provider, model, extraction schema and prompt versions
- per-run character/token limits, rate limits, monthly spend ceiling and kill switch
- retention, residency, legal/privacy and incident-owner decisions
- immutable activation request with independent security/privacy and product approvals
- no automatic enabling of production or restricted documents

Exit: the staging provider may be enabled for synthetic/de-identified evaluation only.

## Sprint 11B — Quality, Safety & Cost Evaluation

- representative synthetic/de-identified CE reports and engine logs
- field-level precision/recall and unsupported-claim rate
- source-quote validity and page/segment linkage
- prompt-injection, malformed-file, cross-tenant and restricted-data tests
- latency, token and cost budgets
- regression suite pinned to model/prompt/schema versions
- human-review usability and override measurements

Exit: all agreed thresholds pass; failures block promotion and remain visible.

## Sprint 11C — Bounded Real-Document Private Pilot

- explicit organization and data-owner authorization
- allowlisted non-restricted document types only
- small case/time/user cohort with mandatory human review
- monitoring, incident response, immediate provider kill switch and rollback
- no autonomous liability, coverage, reserve, settlement or payment decision
- outcome review before any scope expansion

Exit: a separately authorized production-AI decision may be considered. Restricted documents remain a later explicit decision.

## Practical answer

- Synthetic developer use: available now after local provider configuration.
- Shared staging use: after Sprint 11A.
- Real but non-restricted claim documents: after Sprints 11A and 11B pass and Sprint 11C is explicitly authorized.
- Broad production or restricted-document use: only after the bounded pilot demonstrates the required quality, safety, privacy, operational and cost thresholds.
