# ADR-252: Provider-neutral Evidence-family binding for SFTP

## Status

Accepted for Phase 17.6-U implementation.

## Context

The external Evidence-family binding control plane was introduced for SharePoint and Google Drive. Its durable source-item → Document-family semantics are provider-neutral, but the persisted admission lineage was not: each binding required a legacy external-document admission execution and the provider constraint excluded SFTP.

Phase 17.6-T now creates one canonical initial SFTP Evidence Document through a separate, transport-specific admission execution. Copying the entire family-binding stack for SFTP would duplicate mature authority, integrity and receipt logic.

## Decision

Phase U extends the existing `ExternalDocumentSourceEvidenceFamilyBinding` model and service instead of creating an SFTP-specific binding stack.

The binding stores exactly one admission lineage:

- SharePoint / Google Drive: existing `admission_execution_id`;
- SFTP: new `sftp_admission_execution_id`.

A database XOR/provider constraint requires the correct lineage for the provider. Historical SharePoint/Google Drive rows retain their existing identifier and hash semantics.

The service resolves both admission types into one bounded internal lineage projection containing only the facts needed by the generic family anchor.

## Stable SFTP identity

SFTP source identity is derived deterministically from:

- provider kind `sftp`;
- the immutable external-source profile ID;
- the trusted relative-path hash already bound by the Phase-S authorization and reverified by Phase-T integrity.

The raw remote path is never persisted or returned by Phase U. The identity is stable for the same governed path within the same profile and distinct across different profiles or path hashes.

## Integrity

SFTP binding creation requires:

- an integrity-valid Phase-T execution;
- its integrity-valid Phase-S authorization and R/Q/P lineage;
- same organization, profile and Claim;
- an active canonical Document with `document_family_id == document.id`;
- version 1, current state and uploaded/unprocessed status;
- no existing binding for the T execution, stable source identity or Document family.

Binding integrity re-resolves the original provider lineage on every read. Tampering with SFTP authorization or admission lineage therefore invalidates the generic family binding fail-closed.

## Compatibility

Legacy SharePoint/Google Drive scope and completion hashes preserve their previous payload shape. Adding the nullable SFTP lineage field therefore does not reinterpret historical bindings or receipts.

## Authority boundary

Phase U performs no provider/SFTP I/O, no object-storage I/O, no Document mutation, no processing enqueue, no OCR/extraction, no AI, no Claim mutation, no checkpoint advance and no background synchronization.

The family anchor does not grant downstream processing authority.

## Consequence

SFTP Evidence now converges into the existing generic Document-family control plane immediately after initial admission. Later phases can extend processing release and recurring observation without maintaining a parallel SFTP family-binding subsystem.
