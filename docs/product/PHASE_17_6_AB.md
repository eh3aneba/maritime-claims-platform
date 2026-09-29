# Phase 17.6-AB — Controlled SFTP changed-file refresh

Phase AB consumes one human-approved SFTP changed observation into the existing governed refresh quarantine.

## Preconditions

- changed SFTP due-tick observation;
- pending review handoff;
- human `approve_refresh` decision;
- exact current Evidence Document/version unchanged;
- integrity-valid W SFTP lineage.

## Execution

1. Resolve the exact SFTP file target from trusted lineage.
2. Open one bounded read-only SFTP session through the existing content-read adapter.
3. Read the exact file once.
4. Verify byte count against the Y changed observation.
5. Require a digest different from current canonical Evidence.
6. Stage and verify the bytes in observation-refresh quarantine.
7. Persist one immutable shared refresh execution and receipt.

## Replay

Exact replay returns the existing refresh execution and does not repeat the SFTP content read.

## Exclusions

AB does not:
- list directories;
- accept a caller path;
- write/delete/rename remotely;
- create a new Document;
- mutate Claim facts/assessment;
- enqueue processing;
- execute AI.

## Next

Phase AC converts the verified refresh quarantine object into one canonical Evidence version N+1 through the existing admission boundary.
