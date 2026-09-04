# ADR-099 — Technical Review uses current usable evidence state

## Status
Accepted for Phase 13.5A.

## Context
The existing H&M Technical Review intentionally combines two classes of inputs:

1. canonical, human-approved `ClaimFact` values for maintenance/repair facts; and
2. human-reviewed workshop extraction rows for findings, repair options and source opinions that should **not** be promoted into ClaimFacts merely because they were reviewed.

The second class previously remained eligible even if its source document had later been superseded, soft-deleted, failed processing or entered a blocked malware state. A prior workshop opinion could therefore continue to look current after the underlying source was no longer a usable current evidence version.

Technical Review is advisory support. It must never silently convert a source opinion into a causation finding or infer proximate cause.

## Decision
Phase 13.5A keeps the two-layer authority model and hardens evidence admission:

- technical scalar facts continue to come from the current canonical `ClaimFact` read model;
- workshop findings, repair options and suspected-cause opinions may remain reviewed `DocumentExtraction` evidence because an opinion is not a ClaimFact;
- reviewed workshop extraction evidence is admitted into the live Technical Review only when its source `Document` is tenant/claim scoped, current, non-deleted, `processed`, and in a usable malware state;
- `clean` and `legacy_unscanned` are admitted, matching the backward-compatible evidence semantics already used by the deterministic Rules workflow;
- `infected_quarantined`, `scan_error`, failed/pending processing, deleted and non-current source documents are excluded from the live technical state;
- every admitted workshop evidence item exposes document version, processing/security state and an explicit `current_usable` source state;
- the live review exposes a deterministic `evidence_state_fingerprint` derived only from technical inputs: relevant canonical ClaimFact versions/provenance, admitted workshop evidence/version state, and active technical issue state;
- unrelated financial or other non-technical ClaimFacts do not change this fingerprint;
- `generated_at` is excluded from the fingerprint so exact replay of unchanged technical evidence is stable.

## Authority boundary
The fingerprint is a state identity token, not a confidence score, cause probability, coverage opinion or technical finding. A workshop suspected-cause opinion remains labelled and treated as a source opinion requiring independent corroboration or contradiction.

The platform does not autonomously determine proximate cause, coverage, liability, workmanship responsibility, fraud, reserve, settlement, payment, recovery or legal outcome.

## Consequences
- source replacement/deletion, processing failure/quarantine or material canonical technical fact evolution cannot remain invisible to downstream technical review lineage;
- later Phase 13.5 tranches can bind explicit human technical dispositions/snapshots to this fingerprint and reliably identify stale review state;
- legacy processed documents remain visible without weakening quarantine/failure controls;
- no new route, dashboard, causation engine or top-level AI stage is introduced.

## Tests
Phase 13.5A backend acceptance verifies:

- identical live evidence yields the same fingerprint;
- current processed legacy-unscanned workshop evidence remains admitted;
- failed, quarantined, non-current and deleted source documents are excluded;
- admitted evidence exposes source document version/security/processing provenance; and
- a new canonical technical ClaimFact version changes the technical evidence-state fingerprint.

Refs #178
