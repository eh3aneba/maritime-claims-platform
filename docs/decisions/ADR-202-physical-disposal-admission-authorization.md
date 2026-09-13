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

The credential is:

- tenant- and claim-scoped;
- limited to one future execution;
- valid for at most five minutes and never beyond the live quarantine/manifest
  window;
- subject to a second independent retention-admin + MFA approval;
- invalidated if release, manifest or AO evidence drifts before approval.

## Safety boundary

Phase 17.4-A is **authorization only**. It does not:

- delete an S3 object;
- delete a local object;
- mutate document bytes;
- clear or rewrite a document storage key;
- remove a database row;
- consume the authorization.

Database constraints permanently require the Phase 17.4-A record itself to report
no destructive action, no storage write, no S3 delete and no local delete.

## Consequences

A later Phase 17.4-B destructive executor may consume an `authorized` credential
only after it independently revalidates the same release, manifest and all-document
AO bindings. It must increment the execution count exactly once and produce durable
execution evidence. That executor requires separate implementation and merge
authorization.
