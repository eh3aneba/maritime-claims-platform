# Phase 17.6-X — Recurring SFTP observation schedule authority

Phase X opens the existing recurring-observation schedule lifecycle for SFTP Evidence families.

## Preconditions

The Evidence family must already have:
- a canonical SFTP Evidence admitted through T;
- a provider-neutral family binding from U;
- integrity-valid lineage resolvable through W;
- a current Document in the bound family.

## Lifecycle

An Admin with current MFA may:
1. authorize a bounded schedule;
2. replay the exact request idempotently;
3. replace the cadence through a new immutable revision;
4. disable the active revision.

Supported cadence classes remain unchanged:
- hourly;
- every 6 hours;
- every 12 hours;
- daily.

Only one active schedule may exist for a binding.

## Validation boundary

Draft validation runs migration, scoped PostgreSQL concurrency, CI, supply-chain and performance gates while Full Backend remains reserved for the final ready-for-review production head.

## No provider execution

Schedule lifecycle actions do not contact SFTP and do not read or write object storage.

They only persist human authority for future due-tick observation.

## Privacy

Schedule API and audit payloads contain durable hashes/IDs only. Raw remote paths, host/user credential material and secrets are not exposed.

## Production validation

After Phase W merged, Phase X was clean-rewritten onto the merged `main` lineage. The final production head must pass the complete CI, PostgreSQL concurrency, supply-chain, operational-performance, deployment-policy and Full Backend gate set before merge.

## Next

Phase Y consumes an SFTP schedule due tick through the generic dispatch/service-executor pipeline.
