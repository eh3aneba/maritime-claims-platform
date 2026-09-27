# ADR-247: Generation-3 SFTP content custody is separate from checkpoint advancement

## Status
Accepted for Phase 17.6-P.

## Context
Phase 17.6-O can observe one exact SFTP file against the immutable generation-2 checkpoint created by Phase 17.6-N and classify the metadata projection as unchanged, changed, or canonical missing.

A changed metadata projection is not itself durable custody of a new file body. Before a generation-3 checkpoint can exist, the exact changed file must be reread under the governed SFTP boundary, proved, and staged immutably. Combining that reread/staging with checkpoint advancement would collapse network/content authority and control-plane checkpoint authority into one operation.

## Decision
Phase 17.6-P is a separate Admin + MFA operation that consumes only one exact completed integrity-valid Phase 17.6-O `changed` observation.

P:
- revalidates the complete O→N→M→L→K and earlier SFTP lineage;
- derives the exact remote file path and credential reference from persisted lineage only;
- reuses the existing bounded SFTP exact-file content-read adapter/policy;
- enforces the existing 8 MiB content ceiling;
- reconciles reread byte count against O observed metadata;
- rejects a reread that still equals the generation-2 checkpoint digest;
- persists a durable `content_verified` proof before any object-store PUT;
- stages one deterministic immutable generation-3 quarantine object with put-if-absent;
- verifies the staged object by digest and byte count;
- persists requested/content_verified/completed receipts.

## Crash recovery
The lifecycle is:

`requested → content_verified → completed`

The content proof is committed before first PUT. After that commit the execution row is re-locked before storage authority continues.

On replay from `content_verified`:
- if the deterministic object exists and verifies, P completes without another SFTP reread or PUT;
- if it is absent, P rereads the exact file and requires an exact match to the committed content proof before put-if-absent;
- no overwrite or delete authority is granted.

This uses the stronger three-stage custody pattern proven in the equivalent generation-3 external-document restaging flow while preserving the deterministic recovery principles established by the earlier SFTP successor restaging phase.

## Authority boundary
P does not authorize:
- directory listing or alternate-path discovery;
- provider write/rename/delete/mkdir/chmod/chown/touch or arbitrary commands;
- storage overwrite/delete/copy/migration;
- checkpoint creation or advancement;
- Document/Evidence admission;
- parsing/OCR/indexing/downstream processing;
- AI execution or Claim mutation;
- recurring/background synchronization.

## Consequences
The generation-2 M object and N checkpoint remain immutable. P creates only a generation-3 quarantine candidate. A later independently reviewed phase may advance checkpoint custody from generation 2 to generation 3 using P’s verified persisted facts with zero provider/object-storage I/O.
