# ADR-260: Canonical admission of a verified SFTP refresh

## Status

Proposed for Phase 17.6-AC.

## Context

Phase AB produces one integrity-valid SFTP observation-refresh execution in governed quarantine.

The existing refresh admission authorization/execution services are already provider-neutral in behavior. They consume the refresh execution, verify the durable family binding/current Document, read only governed staged storage, perform signature and malware checks, and create the next canonical Document version.

The remaining blockers are provider constraints on refresh-admission authorization and execution persistence.

## Decision

Reuse the existing refresh-admission control plane for SFTP.

Widen only:
- refresh-admission authorization provider constraint;
- refresh-admission execution provider constraint.

Do not add SFTP-specific admission services or provider I/O.

## Execution

The SFTP refresh admission flow:
1. verifies the AB refresh execution and U Evidence-family binding;
2. verifies the prior current Document/version is unchanged;
3. rejects same-content/duplicate refreshed digests;
4. reads the already-governed refresh quarantine object;
5. validates digest, size and file signature;
6. performs a fresh authoritative malware scan;
7. promotes content to canonical Evidence storage;
8. creates exactly one Document N+1 in the same family;
9. makes N+1 the sole current Document;
10. persists one immutable admission execution and receipt.

## Provider boundary

AC performs zero SFTP/provider I/O and never repeats the AB remote content read.

No parsing, extraction, processing enqueue or AI is authorized.

## Compatibility

SharePoint/Google Drive refresh-admission behavior remains unchanged.

## Next

Phase AD will re-enter the new SFTP Document N+1 through the existing generic processing-release boundary and establish the recurring-observation baseline/checkpoint transition after successful admission.
