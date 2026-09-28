# Phase 17.6-U — Provider-neutral Evidence-family binding for SFTP

Phase U binds one completed Phase-T SFTP admission into the existing external Evidence-family control plane.

## Operator flow

1. Complete Phase T for one current human-authorized SFTP file.
2. Select that SFTP admission execution.
3. Provide a request key and binding reason.
4. Phase U revalidates the complete SFTP admission and authorization lineage.
5. The canonical Document must still be current, version 1 and unprocessed.
6. One immutable Evidence-family binding and one receipt are recorded.

## Provider-neutral lineage

The shared binding table now supports exactly one admission lineage:

- `admission_execution_id` for SharePoint / Google Drive;
- `sftp_admission_execution_id` for SFTP.

Both cannot be present and neither can be absent.

## Stable SFTP source identity

The durable SFTP source-item hash is derived from the SFTP provider kind, the source-profile ID and the trusted relative-path hash. Raw paths, storage keys and credentials are not exposed by the binding API or audit event.

The same exact governed path in the same profile yields the same stable identity. A different profile or path hash yields a different identity.

## Safety boundary

Phase U is DB-only. It performs no:

- SFTP stat/list/read/write;
- credential or session operation;
- object-storage read/write/delete;
- Document creation or mutation;
- OCR, parsing, indexing or extraction;
- processing enqueue or AI;
- Claim mutation;
- checkpoint advance;
- recurring synchronization.

## Replay and conflicts

Exact replay of the same request key returns the existing binding.

A second binding for the same SFTP admission execution, stable source identity or Document family conflicts.

Any tampering in the T → S → R → Q → P lineage causes binding reads and creation to fail closed.

## Processing remains blocked

The binding creates the durable family anchor only. The SFTP Document remains uploaded and unprocessed. Phase 17.6-V will prove and, where necessary, adapt the existing generic processing-release boundary for SFTP-bound Evidence.
