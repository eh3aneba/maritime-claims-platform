# ADR-255: SFTP recurring-observation schedule authorization

## Status

Proposed for Phase 17.6-X.

## Context

Phase W made recurring-observation lineage and due-tick persistence provider-neutral while intentionally keeping SFTP schedule authority closed.

The recurring schedule lifecycle itself is already Evidence-family-binding centric and performs no provider I/O.

## Decision

Allow `provider_kind=sftp` in the existing recurring schedule authority model.

No SFTP-specific schedule table, router, service or receipt lifecycle is introduced.

An SFTP schedule uses the same:
- Admin + current MFA authorization;
- bounded cadence set;
- immutable revision chain;
- one-active-schedule-per-binding guard;
- replay semantics;
- replace/disable lifecycle;
- audit boundary.

## Authority boundary

Phase X authorizes cadence only.

Creating, replacing or disabling a schedule performs no SFTP stat/list/content read, no credential resolution/session creation, no object-storage I/O, no Document or Claim mutation, no processing enqueue, no checkpoint change and no AI execution.

The provider-neutral W resolver is consumed only when a later due tick is executed.

## Migration

Migration 0216 widens the existing schedule provider check to include `sftp`.

Downgrade fails closed while any SFTP schedule rows exist.

## Next

Phase 17.6-Y will prove that generic due-tick dispatch/service execution can consume an authorized SFTP schedule and perform the one bounded exact-file stat defined by W.
