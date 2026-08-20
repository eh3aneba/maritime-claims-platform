# External AI Activation Roadmap

## Current capability

The product already has a provider-neutral gateway, an OpenAI adapter using the Responses API and strict Structured Outputs, source-linked extraction candidates, quote verification, confidence fields, append-only feedback and mandatory Approve/Edit/Reject human review. AI candidates never directly update authoritative claim facts. The external provider remains disabled by default, and Sprint 11A blocks restricted documents entirely.

Deterministic tests may still inject local fake providers, but real OpenAI processing is restricted to a separately governed staging environment. Configuration alone is not authorization.

## Sprint 11A — Provider Activation & Evaluation Gate

Implementation status: the application control plane, independent approval ledger, per-document eligibility gate, kill switch and queue-time enforcement are implemented. Shared staging processing still requires the organization to provision and evidence the separate provider project, secret, spend, privacy and incident controls and then complete an authorized activation attempt.

- separate OpenAI staging and production projects and credentials (operational prerequisite; Sprint 11A authorizes staging only)
- secret-manager/environment-only key handling; no database, source or log storage
- explicit document-classification allowlist and restricted-data prohibition by default
- pinned provider, model, extraction schema and prompt versions
- per-run character/token limits, rate limits, monthly spend ceiling and kill switch
- retention, residency, legal/privacy and incident-owner decisions
- immutable activation request with independent security/privacy and product approvals
- no automatic enabling of production or restricted documents

Exit: after the operational prerequisites and independent activation decision are complete, the staging provider may be enabled for synthetic/de-identified evaluation only.

## Sprint 11B — Quality, Safety & Cost Evaluation

Implementation status: the application now provides the version-pinned, content-free case ledger, deterministic threshold calculation, independent reviews, Admin promotion decision and revocation control. The organization must still execute the controlled synthetic/de-identified benchmark against its authorized staging provider and record the observed evidence before promotion.

- representative synthetic/de-identified CE reports and engine logs
- field-level precision/recall and unsupported-claim rate
- source-quote validity and page/segment linkage
- prompt-injection, malformed-file, cross-tenant and restricted-data tests
- latency, token and cost budgets
- regression suite pinned to model/prompt/schema versions
- human-review usability and override measurements

Exit: all fixed thresholds pass, Quality/Risk reviews are independently completed and an Admin records the expiring staging promotion. Failures block promotion and remain visible.

## Sprint 11C — Bounded Real-Document Private Pilot

- explicit organization and data-owner authorization
- allowlisted non-restricted document types only
- small case/time/user cohort with mandatory human review
- monitoring, incident response, immediate provider kill switch and rollback
- no autonomous liability, coverage, reserve, settlement or payment decision
- outcome review before any scope expansion

Exit: a separately authorized production-AI decision may be considered. Restricted documents remain a later explicit decision.

## Practical answer

- Deterministic developer tests: available now with local fake providers and no external processing.
- Shared staging use: after Sprint 11A controls are deployed and an activation attempt is independently authorized.
- Real but non-restricted claim documents: after Sprints 11A and 11B pass and Sprint 11C is explicitly authorized.
- Broad production or restricted-document use: only after the bounded pilot demonstrates the required quality, safety, privacy, operational and cost thresholds.
