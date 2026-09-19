# Phase 17.5-AA — Later external Evidence version admission

Phase AA turns one later, separately human-authorized remote source version into the next immutable
canonical Document version of an existing external Evidence family.

## End-to-end flow

The phase deliberately reuses the existing integration pipeline instead of introducing generation-4 tables:

`S changed observation → T versioned restaging → U checkpoint → V exact-current confirmation → W human authorization → AA canonical N+1 admission`.

AA starts only after Y has established the durable source-item family and Z has established exact-version
processing authority.

## Canonical version semantics

For one verified family:

- vN must be the single current, non-deleted Document;
- AA locks that current row;
- vN is marked non-current with canonical supersession metadata;
- one new Document is created in the same `document_family_id`;
- new `version_number = vN.version_number + 1`;
- `supersedes_document_id = vN.id`;
- prior bytes, provenance and review history remain preserved;
- exactly one Document is current after the transaction.

The immutable Y family-binding record remains the family anchor and v1 provenance snapshot. AA does not
rewrite Y's original receipt or hashes.

## Admission controls

Immediately before canonical write, AA verifies:

- same tenant, Claim, source profile and provider;
- same durable stable source-item identity;
- a new single-use W human authorization;
- authorization is newer than the current canonical Document;
- V observation is still the authorized exact candidate;
- one fresh exact-item metadata read still matches the authorization;
- governed staged bytes match SHA-256 and byte count;
- filename/media signature is valid;
- authoritative malware scan is clean;
- bytes are not already present in Claim Evidence.

Caller-supplied family IDs, version numbers, provider identifiers, storage keys, processing permissions or
AI permissions are schema-rejected.

## Processing and AI

AA creates the new Document in uploaded state and enqueues nothing.

All Documents in a Y-bound external family are subject to the Phase-Z processing-release guard. A release
for vN fails once vN+1 is current. The new current version requires a new exact-version processing release.

Phase Z remains local-processing authority only. External AI still requires the independent AI
runtime/governance authorization.

## Concurrency

AA uses PostgreSQL locking and canonical Document uniqueness so concurrent candidates cannot produce two
current Documents. Dedicated PostgreSQL regressions cover:

- two concurrent attempts from the same expected current version;
- exactly one winning next version;
- exactly one current Document after commit;
- rollback restoring the prior current version when the next-version insert fails.

## Non-goals

AA does not provide automatic remote-change admission, recurring/background sync, broad provider/folder
crawl, OCR/extraction, AI execution, ClaimFact/assessment mutation, coverage/liability/causation/settlement
authority or checkpoint advancement.
