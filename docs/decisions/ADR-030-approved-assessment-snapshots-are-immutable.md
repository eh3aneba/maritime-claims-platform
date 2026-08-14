# ADR-030 — Approved assessment snapshots are immutable

## Status
Accepted — Sprint 7A

## Decision
Once an Initial Assessment version is approved, its sections may no longer be edited in place. New evidence, wording changes, or revised conclusions require generation of a new assessment version.

## Rationale
An approved assessment is an auditable claims snapshot. Allowing post-approval edits would make it impossible to prove what was reviewed and approved at a particular point in the claim lifecycle.

## Consequences
- Approved versions display as locked in the UI.
- The backend rejects section review/edit attempts against approved assessments with HTTP 409.
- Users generate a new version to incorporate later evidence or revised wording.
- Previous approved versions remain intact for audit and comparison.
