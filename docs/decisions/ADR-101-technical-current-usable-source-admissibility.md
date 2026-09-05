# ADR-101 — Technical Review admits only current usable source evidence

## Status
Accepted for Phase 13.5D closeout.

## Context
Technical Review records human investigation dispositions against evidence-grounded technical topics. A reviewed workshop extraction can outlive the source document state that made it usable: the document may later be superseded, deleted, fail processing, become quarantined, or enter a scan-error state.

If such an extraction remains in the live matrix, a prior technical disposition can appear current even though its source is no longer authoritative/usable. If the topic is simply removed, the append-only human lineage can become invisible to the operator.

## Decision
Workshop findings, repair options and suspected-cause opinions are admitted into the current Technical Review state only when the source document is:

- scoped to the same tenant and claim;
- the current document version (`is_current=true`);
- not soft-deleted;
- successfully processed; and
- security-usable (`clean` or backward-compatible `legacy_unscanned`).

Admitted evidence exposes document version, current state, processing state, malware-scan state and an explicit `current_usable` source marker.

If a technical topic with existing human decision lineage is no longer present in current usable evidence or active rule state, Technical Review retains the same stable topic key as a historical row with no current supporting evidence. The historical row:

- is fingerprinted from the current absence/unavailable state;
- becomes `stale` relative to the prior human disposition;
- retains the append-only decision history and latest decision hash;
- requires deliberate re-review before another disposition is recorded; and
- can become `current` only relative to the reviewed absence/unavailable state, not by reinstating the unavailable source.

This uses the existing `TechnicalInvestigationDecision` model and exact state fingerprint/version controls. No second mutable causation state is introduced.

## Failure and recovery behavior
A failed, quarantined, scan-error, deleted or superseded source is excluded from live technical evidence. Prior human lineage is preserved rather than silently transferred or deleted. Operators recover by reviewing the source/version/security change, obtaining replacement evidence where appropriate, refreshing the current Technical Review state, and deliberately re-reviewing the historical topic if a new disposition is required.

Stale writes remain rejected through the existing exact fingerprint/version contract and `409` recovery behavior.

## Authority boundary
Technical source admissibility and human investigation dispositions do not establish proximate cause, coverage, liability, negligence, unseaworthiness, workmanship responsibility, fraud, reserve, settlement, payment, recovery or any legal outcome. Workshop, surveyor and maker opinions remain source opinions.

## Consequences
- Technical decisions cannot silently remain current after their source becomes unusable.
- Historical human reasoning remains visible and auditable even when current evidence disappears.
- Downstream immutable Claim Pack snapshots receive the same current/stale technical lineage without a duplicate authority model.
- Existing current usable legacy-unscanned documents remain supported for backward compatibility.

Refs #179
Refs #154
