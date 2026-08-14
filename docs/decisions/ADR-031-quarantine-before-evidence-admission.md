# ADR-031: Quarantine before evidence admission

## Status

Accepted — Sprint 7B

## Context

Claim evidence is untrusted input. Extension, MIME and basic signature validation reject obvious mismatches but cannot establish that a file is safe for download, extraction or later intelligence processing. A scanner outage must not silently convert an unknown verdict into an accepted document.

## Decision

New uploads are written to a tenant/claim-scoped quarantine key and streamed to ClamAV over the internal Compose network. Only an authoritative clean verdict permits atomic promotion into active evidence storage, creation of the `documents` row and queuing of text extraction.

Malware findings and scanner or promotion failures are fail-closed. Their bytes and limited metadata remain in a separate `quarantined_uploads` table, are audit logged, appear in the claim UI and have no download or processing route. ClamAV port `3310` is not published to the host.

Existing documents migrate as `legacy_unscanned`; historical evidence is not reclassified as clean without a real rescan. Development may explicitly disable scanning for trusted synthetic fixtures, but pilot, staging and production preflight requires it.

## Consequences

- Document processing never receives a newly uploaded file without a clean verdict.
- Scanner outages temporarily reject evidence admission with `503` instead of degrading open.
- Operators must capacity-plan ClamAV signature memory and define quarantine retention/purge procedures.
- A follow-up controlled workflow must rescan legacy evidence and reconcile retained quarantine records.
