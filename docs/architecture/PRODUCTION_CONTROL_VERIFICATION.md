# Production Control Evidence & Independent Verification

## Purpose

This gate connects an attested target architecture to retained evidence that production controls were implemented and independently checked. It is an evidence-governance workflow: it does not run deployment commands, inspect cloud accounts automatically, assert compliance or authorize production traffic.

## Versioned verification profiles

Sprint 10C introduced the immutable `foundational_v1` profile with exactly five controls:

1. identity and access
2. secure evidence storage
3. content-free observability
4. backup and disaster recovery
5. deployment and infrastructure-as-code

Sprint 10D introduces `architecture_v2` for new gates and adds:

6. application security
7. data governance
8. interoperability
9. AI governance

Existing gates are migrated as `foundational_v1`; new gates are created as `architecture_v2`. The profile cannot be changed after gate creation. This avoids retroactively changing the meaning, completion state or canonical hash of a historical five-control verification.

Each submission records an implementation statement, reproducible verification method, rollback plan, owner, implementation time and an allowlisted `artifact://`, `runbook://`, `ticket://` or `monitor://` reference. Secrets, credentials, raw infrastructure artifacts, external URLs and claim content are not accepted.

## Versioned four-eyes lifecycle

1. A Manager/Admin creates one gate from an attested architecture baseline.
2. A Manager/Admin submits version 1 for a required control.
3. A different Manager/Admin verifies or rejects it with a written note; verification also requires a bounded review reference.
4. Rejection freezes that version. A corrected submission becomes the next version and the rejected history remains visible.
5. Completion is blocked until the latest version of every control in the immutable profile is independently verified.
6. Completion freezes a profile-aware canonical SHA-256 snapshot.

The completed summary always states that production certification and go-live authorization are false and that content/secrets are not included. Separate security, privacy, legal, operational acceptance and change-approval decisions remain mandatory.
