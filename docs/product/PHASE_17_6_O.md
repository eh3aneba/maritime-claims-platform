# Phase 17.6-O — Successor-aware exact-file SFTP observation

Phase 17.6-O adds one manually triggered, metadata-only observation against an integrity-valid generation-2 SFTP checkpoint created by Phase 17.6-N.

## Operator semantics
An organization Admin with MFA provides only:
- `request_key`
- `reason`

The system derives the SFTP destination, credential reference, governed remote root, exact relative file path, and generation-2 comparison baseline from persisted lineage. Caller-supplied host/path/credential/generation/content/storage fields are rejected.

The operation performs one bounded exact-file metadata/stat request and returns:
- `unchanged`
- `changed`
- `missing`

Only canonical remote not-found becomes `missing`; permission/authentication/host-key/timeout/path-policy/adapter failures fail closed.

## Generation-2 baseline
The comparison baseline comes from the exact Phase L observation that M restaged and N advanced:
- successor byte size from M/N;
- modified time and metadata identifier hash from L observed metadata;
- deterministic projection and lineage hashes tying the observation to N→M→L→K.

The original K generation-1 metadata is not used as the generation-2 comparison state.

## Safety boundary
This phase performs no:
- remote content read;
- directory listing;
- provider write/mutation;
- object-storage I/O;
- content staging/restaging;
- checkpoint creation/advancement;
- Document/Evidence creation;
- processing/OCR/indexing;
- AI execution;
- Claim mutation;
- recurring/background sync.

Exact replay is idempotent and does not repeat the provider call. Separately keyed manual observations against the same generation-2 checkpoint are permitted.
