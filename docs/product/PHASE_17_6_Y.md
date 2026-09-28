# Phase 17.6-Y — Generic SFTP due-tick service execution

Phase Y proves that an SFTP recurring schedule can use the existing generic scheduler and service-executor path.

## Flow

1. Phase X has an active SFTP recurring schedule.
2. The generic scheduler creates one due-tick dispatch when the schedule becomes due.
3. Dispatch creation performs no SFTP/provider I/O.
4. The configured internal service executor consumes the dispatch.
5. The W recurring-lineage resolver validates the SFTP T/S/R/Q/P lineage.
6. Exactly one exact-file SFTP stat is performed.
7. The generic due-tick observation stores unchanged, changed or missing.
8. One consumption receipt links the dispatch to that observation.

## Replay

Re-consuming the same immutable dispatch returns the existing observation and consumption. It does not perform another SFTP stat.

## Safety

The execution path does not:
- list SFTP directories;
- read file content;
- write/delete remotely;
- read/write staged or canonical object storage;
- mutate Documents or Claims;
- advance checkpoints;
- enqueue processing;
- run AI.

## Service identity

Only the configured internal external-Evidence observer may consume the dispatch. Wrong service identity fails before provider I/O.

## Next

Phase Z widens the review-handoff boundary for SFTP changed/missing due-tick observations.
