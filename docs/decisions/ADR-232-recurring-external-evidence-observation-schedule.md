# ADR-232: Human-authorized recurring exact-item observation schedules

## Status

Proposed by Phase 17.5-AB.

## Context

Phase Y provides a durable provider-agnostic binding between one external source item and one canonical Document family.
Phase AA makes later versions repeatably admissible without overwriting history.

The next integration step is recurring synchronization, but recurring provider access is itself authority. It must never
exist merely because a source profile or Evidence family exists.

## Decision

Phase AB introduces schedule authority only.

An Admin with current MFA may authorize one recurring exact-item observation schedule revision for one Phase-Y family.
The schedule is bound to organization, Claim, profile, exact family binding, stable source-item hash and Document family.

Allowed cadence classes are deliberately bounded:
- hourly;
- every 6 hours;
- every 12 hours;
- daily.

No caller-provided cron expression is accepted and no sub-hour cadence is allowed.

A schedule revision is immutable once authorized. Cadence changes occur through explicit replacement: the prior revision
is disabled and a new revision is authorized with its own request key, actor, reason, timestamps and hashes.

Disabling is immediate, terminal for that revision and auditable.

## No provider execution in AB

AB performs no provider-client construction, token acquisition, remote list, remote metadata read, content read,
remote write/delete, storage read/write/delete, Document mutation, processing enqueue, AI execution, Claim mutation,
checkpoint advancement or background worker execution.

The schedule records authority for a later phase to consume one due tick into one bounded metadata-only observation.

## Integrity

Only one active revision may exist per family binding. PostgreSQL uniqueness plus row locking protects concurrent
enable/replace operations.

Exact replay is idempotent. Altered replay fails closed. Cross-tenant, cross-Claim, wrong-profile, wrong-family or
tampered lineage fails closed.

Every lifecycle transition has an immutable content-free receipt chain.

## Consequences

Recurring synchronization becomes explicitly human-authorized and auditable before any background provider I/O is
introduced. Later phases can consume due ticks without conflating schedule authority with observation, staging,
Evidence admission, processing or AI authority.
