# ADR-256: Reuse generic due-tick dispatch/service execution for SFTP

## Status

Proposed for Phase 17.6-Y.

## Context

Phase W makes recurring observation lineage provider-neutral and Phase X authorizes recurring schedules for SFTP Evidence families.

The downstream due-tick dispatch and service-executor control planes are already binding/schedule centric and do not encode a SharePoint/Google Drive-only execution model. Dispatch persistence accepts `sftp`, dispatch consumption has no provider constraint, and execution delegates to the generic due-tick observation service.

## Decision

Do not introduce an SFTP-specific dispatcher, consumer or worker.

Phase Y proves the existing generic path:

schedule → due-tick dispatch → service-executor consumption → due-tick observation

works unchanged for SFTP.

## SFTP I/O boundary

Dispatch itself remains DB-only.

On first service consumption, the generic observation service resolves the W SFTP lineage and performs exactly one existing exact-file metadata/stat operation.

No directory listing or file-content read occurs.

Exact consumption replay returns the existing observation/consumption and performs no second provider stat.

## Result normalization

The generic observation result model continues to represent:

- unchanged;
- changed;
- missing.

SFTP provider-specific lineage selectors are persisted in the due-tick observation row while legacy SharePoint/Drive selector columns remain null.

## Service identity

The configured internal service executor remains mandatory.

An unconfigured service identity fails before any SFTP metadata read.

## Side-effect boundary

Phase Y performs no object-storage I/O, Document or Claim mutation, checkpoint advance, processing enqueue or AI execution.

## Consequence

If the compatibility proof remains green, SFTP recurring execution converges on the existing generic dispatch/worker architecture without production code duplication.

The next provider-specific seam is review handoff for changed/missing observations.
