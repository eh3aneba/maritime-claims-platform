# Phase 17.5-Y — Durable external Evidence family binding

Phase Y establishes a provider-agnostic lineage anchor between one successfully admitted
Phase-X external source item and one canonical Document family.

## Authority boundary

Phase Y is control-plane/domain-lineage only. It performs no provider client construction,
remote metadata/content I/O, object-storage I/O, local Evidence byte writes, Document
creation or mutation, processing enqueue, OCR/extraction/indexing, AI execution, Claim
mutation, checkpoint advancement, or background synchronization.

The caller supplies only a request key and a human reason. Stable source-item identity,
Claim/profile/provider scope, Document IDs, family identity, version baseline, content
hashes and provider-version hash are derived from verified persisted lineage.

## Binding semantics

A valid binding:

- references one completed, integrity-valid Phase-X admission execution;
- reuses the trusted generation-3 observed provider-item hash as the stable source-item identity;
- verifies the admitted Document is current version 1 and its existing
  `document_family_id` equals the initial Document ID;
- records that initial Document as the current baseline for the durable external source family;
- enforces one source-item binding per tenant/Claim/profile and one binding per Document family;
- is immutable and accompanied by one immutable receipt;
- supports exact request-key replay without side effects; altered replay fails closed.

Phase Y deliberately does not authorize downstream processing. Phase Z remains responsible
for a separate exact-current human processing release.
