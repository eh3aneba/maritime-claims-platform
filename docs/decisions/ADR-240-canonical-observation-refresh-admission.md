# ADR-240: Canonical admission of an authorized recurring external Evidence refresh

## Status

Proposed by Phase 17.5-AJ.

## Context

Phase 17.5-AH consumes one human-approved changed-item refresh authorization, performs one exact remote content read, and stages verified bytes in governed quarantine storage.

Phase 17.5-AI then creates a separate Admin + current-MFA admission authorization bound to:
- the exact completed AH execution and content proof;
- the durable external source-item / Document-family binding;
- the exact canonical current Document ID, version and file hash;
- the staged storage backend, purpose and storage-object-key hash.

AI intentionally has no storage-read, malware, Document, processing, AI, Claim or checkpoint authority.

The remaining boundary is to consume that exact authorization and turn the already-staged bytes into the next canonical Document version without reopening broad provider authority or silently inheriting processing authority.

## Decision

Phase AJ is the canonical mutation boundary for the recurring refresh path.

AJ performs the following sequence:

1. lock and integrity-check the exact AI authorization;
2. lock and revalidate the durable Evidence-family binding;
3. lock the exact current canonical Document and require the AI snapshot to remain current;
4. recover the raw AH staging key only from persisted trusted AH lineage;
5. require SHA-256 of that raw key to equal the AI-authorized storage-key hash;
6. read only that exact governed staged object;
7. verify staged object metadata, SHA-256 and byte count against AH + AI;
8. derive a safe canonical filename from the prior Document plus the authorized MIME class, without a provider call;
9. make a local Evidence quarantine copy;
10. validate the file signature;
11. require a fresh authoritative malware-clean verdict;
12. promote the local copy to canonical Evidence storage;
13. use the existing Phase-AA canonical version transition helper to create exactly one N+1 Document;
14. preserve vN as historical Evidence;
15. persist one immutable AJ execution and one receipt.

## No provider I/O

AJ does not construct a provider client, acquire provider tokens, list remote items, read remote metadata, read remote file content, or write/delete remote content.

A source change after AH is handled by a later recurring observation cycle. AJ never silently retargets an AI authorization to another remote version.

This differs intentionally from Phase AA, whose execution performs a fresh exact-item metadata read immediately before admission. The recurring AH → AI → AJ chain already captured and staged the exact changed bytes before the separate human admission authorization, so AJ revalidates the immutable staged proof rather than reopening provider authority.

## Canonical Document invariant

AJ reuses the existing family-version transition helper introduced by Phase AA:

- vN must still be the exact current Document authorized by AI;
- vN is marked historical, never overwritten;
- vN+1 uses the same document_family_id;
- vN+1 has version_number = vN + 1;
- vN+1.supersedes_document_id = vN.id;
- exactly one non-deleted current Document exists after the transition.

The AI authorization is one-use. The immutable AI authorization row is not rewritten into a consumed status: consumption is represented by exactly one immutable AJ execution whose authorization_id is unique. PostgreSQL row locking on the exact authorization plus family/current-Document locking prevents concurrent consumers from producing competing N+1 versions. This preserves Phase-AI authorization history while still proving single consumption.

## Security verification

The AH staged object is not treated as canonical Evidence merely because it was successfully staged.

AJ independently requires:
- staged storage backend identity consistency;
- storage-key hash consistency;
- content SHA-256 and byte-count consistency;
- allowed file type and MIME;
- file-signature validation;
- a fresh authoritative malware-clean verdict.

The execution records a security-verification hash binding the content proof, MIME, validated suffix, malware verdict and malware scan timestamp.

## Failure and rollback

AJ fails closed before canonical mutation if the AI authorization, AH lineage, family binding, current Document or staged content proof has drifted.

If signature or malware verification fails, no new Document is admitted.

If local canonical storage or database mutation fails after a temporary copy is created, the database transaction is rolled back and any uncommitted quarantine/canonical object is removed. The prior vN remains current.

Exact replay of a committed AJ execution returns the same immutable execution and does not reread staged bytes, rerun malware scanning, or create another Document.

## Processing and external AI authority

AJ creates vN+1 in uploaded state and enqueues nothing.

A Phase-Z processing release for vN does not transfer to vN+1. The new exact version requires its own processing release.

External AI authority remains independently governed and is not granted or executed by AJ.

AJ performs no ClaimFact, assessment, chronology, coverage, liability, causation, settlement, checkpoint or background-sync mutation.
