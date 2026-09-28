# ADR-253: Reuse the generic processing-release boundary for SFTP Evidence

## Status

Proposed by Phase 17.6-V compatibility proof.

## Context

Phase 17.6-U makes the external Evidence-family binding control plane provider-neutral and allows an initial SFTP Document to become a normal bound Evidence family.

The downstream `ExternalDocumentSourceProcessingRelease` control plane was designed around the generic family binding and exact current Document version. Its persisted model does not encode a SharePoint/Google Drive provider restriction.

## Decision

Do not introduce an SFTP-specific processing-release model, service or router.

Phase V proves that the existing generic processing-release boundary operates unchanged for SFTP-bound Evidence by exercising the full T → U → release path.

A release continues to authorize only local text processing for one exact current Document version. It does not authorize external AI processing.

## Required invariants

Before release:

- SFTP Evidence remains `uploaded` and unprocessed;
- retry/enqueue is rejected by the processing guard.

During release:

- the generic family-binding integrity path revalidates the complete SFTP T/S/R/Q/P lineage through U;
- the exact current Document and version are verified;
- no SFTP/provider I/O is performed;
- no object-storage I/O is performed;
- no Document or Claim mutation occurs;
- no processing job is enqueued;
- AI authority remains false.

After release:

- the existing processing guard recognizes the exact active release;
- local processing may be enqueued by the normal processing endpoint;
- exact replay remains idempotent;
- revocation removes processing authority;
- any later integrity failure in the SFTP family-binding lineage causes release resolution to fail closed.

## Consequence

If the compatibility tests pass, Phase V requires no production processing-release refactor. SFTP converges fully into the existing generic downstream-processing authority boundary.

Phase 17.6-W may therefore focus solely on the next provider-specific seam: recurring-observation lineage.
