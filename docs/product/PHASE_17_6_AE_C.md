# Phase 17.6-AE-C — Production restart/replay and recovery acceptance

AE-C closes the production reliability loop for SFTP.

## Restart rule

A process restart clears in-memory provider adapters, not durable authority.

For an exact previously completed request:
- content proof replays without another file read;
- approved refresh replays without another remote read/quarantine write;
- canonical admission replays without another Document version;
- recurring baseline transition replays without another transition.

## Production adapter boundary

The disabled-by-default AE-A live SFTP registration is exercised through the real governed API/service persistence boundaries using a deterministic runtime substitute.

This proves the production registration layer does not bypass:
- human authority;
- host-key/credential/session lineage;
- exact-file scope;
- receipt/audit persistence;
- idempotency.

## Recovery

Failures before a durable commit remain fail-closed. No recovery path may:
- silently retry a remote content read under a new authority;
- reuse stale human approval after lineage drift;
- leave two current Documents;
- advance a recurring baseline without explicit AD transition.

## Final acceptance

The clean AE-C head must pass scoped PostgreSQL CI, Full Backend, supply-chain, performance, deployment-policy and browser acceptance before production closure.
