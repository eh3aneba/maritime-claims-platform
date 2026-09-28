# Phase 17.6-S — Initial SFTP Evidence admission authorization

Phase S is the human approval boundary immediately before an SFTP file is allowed to become canonical Claim Evidence.

## Operator flow

1. Select one Claim.
2. Select the latest completed Phase R observation for the governed SFTP file.
3. The observation must be `unchanged`.
4. Provide a request key and authorization reason.
5. The service locks the exact generation-3 checkpoint, revalidates the full R → Q → P lineage and confirms the R observation is still latest.
6. One immutable authorization and one immutable authorization receipt are stored.

## Bound facts

The authorization records:
- Claim/profile IDs;
- R/Q/P internal IDs;
- exact metadata projection/path hashes;
- content SHA-256 and byte count;
- storage object key hash only;
- checkpoint/candidate/observation integrity hashes;
- human actor, reason and decision hashes.

It does not return raw SFTP paths, credentials, session data, file content or raw storage keys.

## Zero-I/O rule

Phase S performs no SFTP/provider or object-storage operation. It creates no Document/Evidence and releases no OCR, indexing, processing or AI authority.

## Currentness

A newer R observation, whether unchanged, changed or missing, makes an older R observation ineligible for a *new* S authorization.

Existing historical authorizations are not rewritten. Phase T must check currentness again immediately before admission.

## Next phase

Phase 17.6-T may consume one still-current S authorization, verify governed staged bytes and security, and create exactly one canonical initial SFTP Evidence/Document v1.
