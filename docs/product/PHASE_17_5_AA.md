# Phase 17.5-AA — Later external Evidence version admission

Phase AA turns one later, separately human-authorized remote source version into the next immutable canonical
Document version of an existing external Evidence family.

## End-to-end flow

AA reuses the repeatable trusted external-source stages:

`S changed observation → T versioned restaging → AA human authorization → AA canonical N+1 execution`

Phase U/V/W are intentionally not repeated for later versions because Phase U enforces one generation-3 successor
checkpoint per Phase-R predecessor. AA therefore adds no generation-4 checkpoint tables.

## Human authorization boundary

AA authorization is a separate immutable record and receipt bound to:

- organization, Claim, profile and Y family binding;
- exact stable source-item identity;
- exact completed Phase-S changed observation;
- exact completed Phase-T staged candidate;
- candidate content proof/completion hashes;
- exact expected current Document ID/version/file hash;
- actor, reason and request key.

Authorization itself performs no provider I/O, storage I/O, Document mutation, processing enqueue, AI execution,
Claim mutation, checkpoint advancement or background synchronization.

## Canonical execution

Immediately before canonical write, AA execution:

- locks and revalidates the authorization and Y family;
- verifies the expected prior Document is still the exact current version;
- performs one fresh exact-item metadata read and requires exact equality with the authorized candidate;
- verifies governed staged SHA-256 and byte count;
- validates filename/media signature;
- requires a fresh authoritative malware-clean verdict;
- rejects same-content Claim Evidence duplicates;
- creates one new Document in the existing family with deterministic N+1 and
  `supersedes_document_id = vN.id`;
- preserves the prior Document as historical Evidence;
- establishes exactly one current Document.

Exact execution replay is idempotent and does not repeat provider/storage mutation. Altered replay fails closed.

## Processing and AI

AA creates the new Document in uploaded state and enqueues nothing.

Phase-X Evidence is protected from processing immediately after initial admission, even before Y binding. Once Y
exists, every Document in that family is subject to the Phase-Z exact-version processing-release guard.

A release for vN fails once vN+1 is current. The new current version requires a new exact-version processing release.
Phase Z remains local-processing authority only; external AI still requires its independent runtime/governance
authorization.

## Concurrency

AA uses PostgreSQL locking and canonical Document uniqueness. Dedicated PostgreSQL regressions cover concurrent
next-version transition and rollback restoration. Authorization also snapshots the expected prior current version,
so two separately authorized candidates cannot both become N+1.

## CI capacity

The backend suite is distributed across eight deterministic shards while retaining the existing 25-minute per-shard
timeout. This prevents test-suite growth from silently weakening the timeout gate.

## Non-goals

AA does not provide automatic remote-change admission, recurring/background sync, broad provider/folder crawl,
OCR/extraction, AI execution, ClaimFact/assessment mutation, coverage/liability/causation/settlement authority
or checkpoint advancement.
