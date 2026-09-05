# ADR-105: Recovery counterparties and time-bar scenarios remain human-controlled

- Status: Accepted for Phase 13.7A
- Date: 2026-09-05
- References: #189, #154, PR #190

## Context

MCRI already had the 12C Recovery & Time-bar Intelligence engine. That engine builds immutable source-linked snapshots and candidate evaluations from reviewed claim facts and preserves separate human dispositions. It deliberately does not determine liability, recoverability, governing law, limitation, waiver, suspension, extension, jurisdiction or settlement.

For production claim handling, one primary recovery candidate and one primary time-bar evaluation are not enough. A handler may need to preserve several potential counterparties and several alternative contractual/statutory time-bar hypotheses at the same time while the evidence and legal analysis are still developing. Treating one candidate as the platform answer would create unsafe legal authority.

## Decision

### 1. Potential recovery counterparties are human allegation context only

A `RecoveryCounterparty` is an append-only human-created record of a possible recovery target, its role, allegation/investigation basis and source reference. It is not a finding of fault, liability, entitlement or recoverability.

Each logical counterparty has a stable key and immutable versions. A revision creates a new row linked to the prior row and requires the exact latest record hash. Historical versions are never rewritten.

### 2. Alternative time-bar scenarios are explicit human hypotheses

A `TimebarScenario` records only inputs deliberately supplied by an authorized handler:

- scenario title and legal/factual basis;
- source reference and optional current claim document version;
- optional current recovery counterparty version;
- human-selected anchor date;
- period value and unit;
- optional extension/tolling assumption and its stated basis;
- assumptions and uncertainty.

MCRI does not select the governing law, legal rule, trigger event, period, extension or tolling effect. Several alternative scenarios may coexist for the same claim.

### 3. Candidate deadline is calendar arithmetic, not legal authority

The platform calculates `candidate_deadline` only by applying deterministic calendar arithmetic to the human-entered anchor, period and optional extension assumption. The client cannot submit a candidate deadline directly.

The candidate remains non-authoritative even if the arithmetic is correct. It is displayed as a review aid and cannot by itself establish a legal time bar.

### 4. Confirmed/overridden deadline is a separate human/legal review lineage

Only a Claims Manager or Admin may record a `TimebarScenarioReview`.

- `confirm` adopts the immutable candidate date after human/legal review;
- `override` records a separately verified human deadline and requires its own source reference;
- `review_needed` records that no deadline has been accepted yet;
- `reject` rejects the scenario without creating a confirmed deadline.

Reviews are append-only, bind to the exact scenario hash and form a previous-review-hash chain. A review never rewrites the scenario that was reviewed.

### 5. Source provenance is optional but explicit

Every counterparty/scenario requires a human-readable source reference. It may additionally bind to one exact current usable claim document version.

Document-bound records snapshot document id, family id, version and file hash. If that document family later evolves, the historical record remains visible but becomes `stale`; if the source disappears it becomes `source_unavailable`. New legal review of stale/unavailable scenarios fails closed and requires a deliberate new scenario version against current evidence.

A record without a document binding is explicitly `reference_only`; the platform does not pretend it has stronger provenance than the user supplied.

### 6. Existing 12C intelligence remains canonical and separate

Phase 13.7A does not replace or duplicate the existing Recovery/Time-bar snapshot/evaluation/decision engine. The mature counterparty/scenario workflow is an additional human hypothesis/review layer in the same `recovery_timebar` module.

Existing 12C evaluations remain source-linked decision support. Scenario reviews remain human legal review. Neither domain automatically writes liability, settlement, payment, reserve, recovery receipt or external correspondence.

### 7. Concurrency and tenant boundaries fail closed

Counterparty and scenario revisions require the exact current record/scenario hash. Claim-level write locking serializes competing writes. Cross-tenant, cross-claim, historical-counterparty and non-current-document references are rejected.

No stale write is auto-rebased and no source is silently substituted.

## Failure and recovery contract

- stale counterparty/scenario hash -> HTTP conflict; reload and deliberately create the next version;
- historical counterparty referenced by a new scenario -> rejected; select the latest version;
- superseded/unprocessed/unusable document selected as a source -> rejected;
- source evolves after scenario creation -> scenario remains historical, source state becomes stale, and further legal review is blocked;
- confirm with a client-supplied different date -> rejected; use explicit override;
- override without verified date or source reference -> rejected;
- handler attempts Manager/Admin legal review -> forbidden by RBAC;
- evidence or legal analysis changes after confirmation -> prior review remains immutable; create/revise the scenario and record a new deliberate review.

## Consequences

MCRI can now represent uncertainty instead of collapsing it into one legal answer. Recovery leads, competing time-bar hypotheses, source evolution and human legal confirmation are auditable without granting the platform authority to decide liability or limitation.