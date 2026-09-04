# ADR-097: Requirement evidence state and human decision lineage

**Status:** Accepted

## Context

Phase 13.4 matures the existing missing-evidence and evidence-completeness workflow rather than adding another evidence product surface. `ClaimDocumentRequirement` is already the operational read model used by the deterministic rules engine, readiness calculation, document requests and downstream claim workflows.

The earlier workflow stored human acceptance of equivalent evidence directly on that mutable requirement row. That is sufficient for a current-state view, but it is not sufficient for production-mature review when the underlying evidence can evolve. A canonical `ClaimFact` may be replaced by a later reviewed version; a direct document may be uploaded, processed, superseded, quarantined or deleted; and a handler may re-review the same requirement after the evidence changes.

A current workflow status such as `missing`, `received`, `under_review`, `accepted` or `superseded` describes the operational outcome. It must not be treated as the identity of the evidence state that a human actually reviewed.

## Decision

### 1. Keep one operational requirement read model

`ClaimDocumentRequirement` remains the single current operational read model. Phase 13.4B does not introduce a second rules engine, a second readiness model or a new top-level evidence domain.

A companion `ClaimDocumentRequirementState` stores only the identity of the underlying reviewable evidence state:

- a canonical `state_fingerprint`; and
- a monotonic `state_version`.

The fingerprint is derived from the deterministic requirement definition plus current relevant evidence identity, including the matched document/version/security/processing state and the permitted canonical equivalent `ClaimFact` candidates and their versions. Mutable workflow outcome labels are not part of the evidence identity.

### 2. Human equivalent-evidence decisions are append-only

Each explicit equivalent-evidence disposition is recorded in `ClaimDocumentRequirementDecision` as an append-only record containing:

- requirement state fingerprint/version;
- decision number;
- exact canonical `ClaimFact` id/version;
- source document id/version where available;
- reviewer and review note;
- previous decision hash; and
- current decision hash.

The mutable requirement row continues to expose the current result for downstream workflows, while the decision table preserves review history.

### 3. Human writes use optimistic concurrency

An equivalent-evidence acceptance must submit the exact requirement `state_fingerprint` and `state_version` displayed to the handler together with the exact canonical `ClaimFact` version reviewed.

If either state has changed before submission, the server rejects the write with a conflict and requires the handler to refresh and review the current evidence. The server does not silently transfer an old human judgment to new evidence.

### 4. Replay and re-review are different operations

An exact transport replay of the same human decision against the same evidence state is idempotent and returns the existing decision rather than creating duplicate audit history.

A semantically changed decision against the same evidence state requires an explicit deliberate re-review signal and appends a new hash-chained decision. Re-review never overwrites the earlier disposition.

### 5. Direct evidence and equivalent evidence remain distinct

A usable current direct document is preferred as the current evidence path. A prior equivalent-evidence decision remains in history but does not override usable direct evidence.

If that direct evidence later becomes unavailable, a prior equivalent-evidence acceptance may resume only when the exact canonical `ClaimFact` version originally reviewed is still current and still qualifies as an allowed equivalent candidate.

If the previously accepted canonical fact changes or disappears, the current requirement becomes stale/superseded and no longer contributes to readiness until a human explicitly reviews the current evidence again.

### 6. Existing decisions are preserved on migration

The migration creates current state rows for existing requirements and converts legacy accepted-equivalent state into an initial append-only decision where the underlying fact can be resolved. Runtime synchronization then advances the evidence-state version when the current evidence differs from the migration seed.

## Authority boundary

This lineage mechanism records and protects human review. It does not determine whether substitute evidence is substantively sufficient without a human decision, and it does not determine coverage, liability, causation, fraud, reserve, settlement, payment, recovery, legal outcome or source truth.

The rules engine may identify deterministic candidates and evidence-state changes. The handler remains responsible for accepting equivalent evidence and for any re-review after the evidence evolves.

## Operator surface

Phase 13.4B exposes the state token and decision history through the existing rules API. It does not create another dashboard or route family. Phase 13.4C will consume this lineage inside the existing Evidence Matrix / missing-evidence operator workflow and align English/Persian presentation and recovery states.

## Consequences

- stale human writes fail closed instead of silently applying to changed evidence;
- prior review history is preserved and hash chained;
- exact retries are safe;
- deliberate re-review is auditable;
- direct-document takeover and later evidence loss can be reconciled without deleting prior human decisions;
- downstream readiness continues to use the existing requirement read model; and
- Phase 13 remains focused on maturing one H&M workflow rather than accumulating new feature surfaces.
