# Phase 17.6-AC — Canonical SFTP refresh admission

Phase AC converts an integrity-valid AB refresh quarantine object into canonical Evidence version N+1.

## Preconditions

- completed AB SFTP refresh execution;
- active U Evidence-family binding;
- exact prior current Document/version unchanged;
- refreshed digest differs from current canonical Evidence;
- no duplicate refreshed digest already exists in the Claim.

## Admission

A human-authorized admission:
- reads only governed refresh quarantine;
- verifies digest/size;
- validates file signature;
- performs a fresh authoritative malware scan;
- creates exactly one new Document version in the same family;
- supersedes the prior current version.

## Provider boundary

No SFTP session or remote read occurs during AC.

The single remote read belongs only to AB.

## Downstream state

The new Document is canonical but remains `UPLOADED`.

No processing job or AI execution is created automatically.

## Next

Phase AD will prove the new SFTP Document N+1 reuses the generic processing-release boundary and advances the recurring observation baseline only through explicit governed authority.
