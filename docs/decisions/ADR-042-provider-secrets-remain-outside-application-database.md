# ADR-042: Provider secrets remain outside the application database

## Status

Accepted

## Decision

Email provider adapters persist a deployment secret reference, selected-folder boundary and canonical read-only capabilities. They never persist OAuth access/refresh tokens and cannot request send, write, delete, archive or full-mailbox capabilities. Adapter runs are bounded, idempotent and checkpointed with one-way hashes.

## Consequences

- Provider credential rotation remains an infrastructure responsibility.
- A database disclosure does not directly disclose provider bearer tokens.
- Provider-specific workers must translate the canonical capability manifest without widening it.
- Message admission still passes through the existing normalized ingestion gateway.
