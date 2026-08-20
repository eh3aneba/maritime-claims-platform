# Production Architecture Baseline

## Purpose

The baseline records the difference between the pilot system and an accountable production target. It deliberately preserves missing and partial controls. Attestation means the nine domains were reviewed; it does not mean they were implemented, tested, compliant or approved for go-live.

## Required domains

| Domain | Baseline question |
| --- | --- |
| Identity & access | Are tenant, workforce, privileged-access and separation-of-duty controls defined? |
| Application security | Are secure delivery, vulnerability, dependency and runtime boundaries defined? |
| Evidence storage | Are encryption, immutability, quarantine, retention and recovery controls defined? |
| Observability | Are content-free metrics, logs, traces, alerts and incident ownership defined? |
| Backup & DR | Are recovery objectives, isolated backups and restoration verification defined? |
| Data governance | Are purpose, residency, retention, deletion, legal hold and exit responsibilities defined? |
| Deployment & IaC | Are reproducible environments, secrets, change control and rollback defined? |
| Interoperability | Are provider adapters, API contracts, idempotency and integration failure modes defined? |
| AI governance | Are provider boundaries, source linkage, human review, evaluation and model-change controls defined? |

Each domain records `missing`, `partial`, `implemented` or `not_applicable`, plus target architecture, residual risk, accountable owner, target date and optional bounded evidence reference.

## Attestation semantics

- all nine domains must be documented
- any missing or partial domain produces `attested_with_gaps`
- the canonical snapshot includes `production_certification: false`
- attestation is Manager/Admin-only and immutable
- a new baseline—not a rewrite—is required after material remediation

Production implementation, independent evidence verification, security/privacy/legal approvals and a separate go-live decision remain outside this phase.
