# ADR-108 — Initial Assessment history and bounded cross-domain consolidation

**Status:** Accepted for Phase 13.8B implementation

## Context

Phase 13.8A bound each newly generated Initial Assessment to a deterministic authoritative source-state fingerprint and blocked stale review/approval writes. The remaining 13.8B maturity gap is operator/audit access to historical versions and a bounded view of current Technical, Financial/Reserve and Recovery/Time-Bar handling state.

Initial Assessment must not become a second authority for technical causation, financial dispositions, reserve setting, recovery/legal conclusions, settlement, payment or claim closure.

## Decision

### 1. Version history is explicit and claim scoped

The Assessment API exposes:

- `GET /claims/{claim_id}/initial-assessment` — latest assessment only;
- `GET /claims/{claim_id}/initial-assessment/history` — compact descending version history;
- `GET /claims/{claim_id}/initial-assessment/versions/{assessment_id}` — one specific historical/current version.

Every returned Assessment version declares:

- `is_latest`;
- `latest_version`;
- its own persisted status and preliminary/final classification;
- `source_state` (`current`, `stale`, `legacy_unbound`);
- the persisted source fingerprint and approved-content digest where available.

A historical version is never silently replaced, promoted or rewritten when a later version is generated.

### 2. Source currency and latest-version semantics are separate

`is_latest=false` means a newer Assessment version exists.

`source_state=stale` means the authoritative source state used by that version has evolved.

Those conditions are independent. Two versions can remain bound to the same still-current source fingerprint while only one is latest. This distinction prevents the UI or downstream reporting from treating "historical" and "stale" as synonyms.

### 3. Cross-domain consolidation is a live read-only adjunct

Assessment responses include `current_domain_status`, a non-persisted projection of what the canonical workspaces currently report:

- Technical: topic and human-decision state from the canonical Technical review service;
- Financial: current recorded cost-review and financial-flag state, without triggering Financial sync or mutation;
- Reserve: latest authoritative reserve-history reference;
- Recovery/Time-Bar: the existing governed downstream human-record projection already used for recovery reporting.

This projection is explicitly labelled `read_only_cross_domain_projection`.

It is **not** included in the immutable approved Assessment content digest and does not rewrite historical Assessment content. Its purpose is to help the operator understand the current claim-handling context while viewing any Assessment version.

### 4. GET remains read-only

Assessment retrieval must not synchronize financial evidence, create decisions, create audit rows, change reserve, update recovery lineage, or mutate any canonical workspace. Financial status therefore reads currently recorded financial rows rather than invoking the mutating `build_financial_review`/sync path.

### 5. Authority remains canonical

Initial Assessment does not determine or supersede:

- coverage;
- causation;
- liability/fault;
- recoverability/subrogation entitlement;
- governing law or authoritative time-bar effect;
- reserve amount or adequacy;
- settlement amount/authority;
- payment approval;
- claim closure.

Technical, Financial/Reserve, Recovery/Time-Bar, Adjustment, Settlement and Payment retain their existing authority boundaries and human controls.

## Consequences

- Auditors and operators can navigate immutable historical Assessments without losing latest-version context.
- Current canonical handling state is visible next to historical snapshots without pretending it was part of the historical approved record.
- Recovery consolidation reuses an existing governed human-record projection instead of introducing a parallel recovery engine.
- Phase 13.8C can add EN/FA/RTL history navigation and the full MT ORION source-evolution browser acceptance on top of stable API semantics.
