# ADR-202 — Physical-disposal admission authorization

## Status

Accepted for Phase 17.4-A.

## Context

Phase 17.2 established retention/disposal governance through a final, human-approved
release review. Phase 17.3 established durable recovery-storage ownership and an
independent document-level health qualification (AO). Neither phase intentionally
created a credential that a destructive executor could consume.

The remaining boundary is sensitive because the release decision is claim-scoped,
while authoritative-storage health is document-scoped. A physical-disposal executor
must never infer that one healthy document proves the whole manifest is safe to act
on.

## Decision

Phase 17.4-A introduces a bounded **physical-disposal admission authorization**.

An admission request is allowed only when:

1. the 17.2-H release review is approved and its stored review and approval hashes
   remain valid;
2. the live quarantine stage and immutable execution manifest revalidate without
   drift;
3. every document row in the manifest has exactly one current, qualified 17.3-AO
   durable authoritative-storage health qualification;
4. each AO qualification still matches the live Phase AN durable recovery-storage
   snapshot; and
5. manifest file hash, size and storage-key fingerprint match the AO evidence.

The credential stores a canonical, deterministically ordered JSON binding set for
all manifest documents. Each document binding carries the document ID, AO
qualification ID/hash, Phase AN ratification ID/hash, integrity proof hash, file
hash, byte size, storage-key fingerprint and manifest row fingerprint. The whole set
is SHA-256 bound into the admission authorization.

The credential also binds a canonical hash of the material governance actor set.
The second approver must be independent from the Phase 17.4-A requester, the final
release-review requester and approver, quarantine creator, manifest creator, dry-run
creator and attester, and the original disposal-authorization requester and approver.
The actor set is re-derived before approval; any lineage drift invalidates the
credential.

Each lifecycle transition emits a separate append-only, SHA-256 hash-chained receipt.
Receipts cover request, authorization, rejection, expiry and invalidation, bind the
authorization/document/actor-set hashes and previous receipt hash, and preserve the
same non-destructive safety flags as the credential. Exact replay does not create a
second receipt.

The credential is:

- tenant- and claim-scoped;
- limited to one future execution;
- valid for at most five minutes and never beyond the live quarantine/manifest
  window;
- subject to a second independent retention-admin + MFA approval;
- invalidated if release, manifest, actor lineage or AO evidence drifts before
  approval.

A recovery-storage inspection failure is treated differently from semantic drift.
If the authoritative recovery store is temporarily unavailable, the request/approval
fails as retryable and the transaction is rolled back. A pending credential is not
expired, invalidated or otherwise consumed merely because storage inspection was
unavailable.

## Safety boundary

Phase 17.4-A is **authorization only**. It does not:

- delete an S3 object;
- delete a local object;
- mutate document bytes;
- clear or rewrite a document storage key;
- remove a database row;
- consume the authorization.

Database constraints permanently require the Phase 17.4-A record and its lifecycle
receipts to report no destructive action, no storage write, no S3 delete and no local
delete.

## Consequences

A later Phase 17.4-B destructive executor may consume an `authorized` credential
only after it independently revalidates the same release, manifest and all-document
AO bindings. It must increment the execution count exactly once and produce durable
execution evidence. That executor requires separate implementation and merge
authorization.
