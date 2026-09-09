# ADR-167 — Reversible recovery authority-switch rehearsal

## Status
Accepted for Phase 17.3-F.

## Context
Phase 17.3-E proved that an approved recovery candidate can be materialized into an isolated shadow namespace and independently verified without changing authoritative evidence. The next risk to exercise is the *control-plane transition itself*: can the system bind an exact source authority and an exact recovery candidate, require independent human activation, simulate the transition, and then prove rollback?

Performing a real cutover at this stage would introduce a materially larger failure domain: `Document.storage_key` mutation, active-backend switching, production read-path changes, partial cutover recovery, and irreversible evidence-authority ambiguity.

## Decision
Introduce `EvidenceRecoveryAuthoritySwitchRehearsal` and append-only `EvidenceRecoveryAuthoritySwitchReceipt` records.

A rehearsal is bound to one exact:
- tenant, claim and document;
- shadow promotion;
- approved promotion attestation;
- recovery replica and restore rehearsal;
- restore verification and latest shadow verification;
- promotion-plan/configuration lineage;
- source-authority fingerprint and shadow-candidate fingerprint.

The bounded state machine is:

`prepared -> activated -> rolled_back`

with fail-closed `expired` and `invalidated` states.

`activated` is **virtual only**. It changes only the rehearsal's virtual authority class/fingerprint. It does not modify application evidence authority.

Preparation creates a maximum 30-minute activation lease, bounded by the parent promotion-attestation expiry. Activation requires a different local Admin from the preparer and current-tenant MFA. Source, remote recovery object, restore staging, promotion lineage, shadow bytes and latest shadow verification are freshly revalidated before activation.

Rollback is risk-reducing and remains permitted after the activation lease or parent attestation time window has elapsed, but it still revalidates the pinned evidence lineage. A drifted lineage becomes `invalidated` rather than being silently accepted.

Every successful or terminal transition emits an immutable hash-bound receipt. Receipts contain fingerprints/hashes and transition semantics, not raw storage paths.

## Hard safety boundary
Phase 17.3-F does **not**:
- rewrite `Document.storage_key`;
- change the active storage backend or read path;
- overwrite, move, archive or delete authoritative evidence;
- issue S3 COPY, DELETE or lifecycle mutations;
- enable dual-write admission;
- create a production cutover token;
- grant the shadow candidate authoritative claim/evidence status.

Database constraints pin `cutover_performed=false`, `authoritative_storage_changed=false`, `document_storage_key_mutated=false`, and `active_backend_changed=false` on the rehearsal. Transition receipts independently pin the first two safety flags false.

## Consequences
This tranche proves cutover-shaped governance and rollback semantics while keeping the production authority boundary unchanged. It gives a future real-cutover design an auditable contract and failure model without prematurely introducing destructive or authority-changing behavior.

A later phase may consider a separately approved, tightly bounded real cutover only after atomic pointer semantics, read-path behavior, rollback recovery, concurrent-write exclusion, partial-failure reconciliation and operational break-glass controls are independently designed and tested.