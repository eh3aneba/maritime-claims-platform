# Production Control Evidence & Independent Verification

## Purpose

This gate connects an attested target architecture to retained evidence that foundational production controls were implemented and independently checked. It is an evidence-governance workflow: it does not run deployment commands, inspect cloud accounts automatically, assert compliance or authorize production traffic.

## Foundational controls

The first gate requires exactly five controls:

1. identity and access
2. secure evidence storage
3. content-free observability
4. backup and disaster recovery
5. deployment and infrastructure-as-code

Each submission records an implementation statement, reproducible verification method, rollback plan, owner, implementation time and an allowlisted `artifact://`, `runbook://`, `ticket://` or `monitor://` reference. Secrets, credentials, raw infrastructure artifacts, external URLs and claim content are not accepted.

## Versioned four-eyes lifecycle

1. A Manager/Admin creates one gate from an attested architecture baseline.
2. A Manager/Admin submits version 1 for a required control.
3. A different Manager/Admin verifies or rejects it with a written note; verification also requires a bounded review reference.
4. Rejection freezes that version. A corrected submission becomes the next version and the rejected history remains visible.
5. Completion is blocked until the latest version of every required control is independently verified.
6. Completion freezes a canonical SHA-256 snapshot.

The completed summary always states that production certification and go-live authorization are false and that content/secrets are not included. Separate security, privacy, legal, operational acceptance and change-approval decisions remain mandatory.
