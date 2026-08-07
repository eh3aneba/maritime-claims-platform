# ADR-017 — Keep maintenance/workshop repeatable evidence separate from scalar claim facts

**Status:** Accepted  
**Date:** 2026-08-07

## Decision
PMS job rows, workshop damage findings, repair-option rows and workshop recommendations remain human-reviewable repeatable evidence rather than scalar `claim_facts`. Maintenance scalars such as running hours since overhaul, last overhaul date, recommended interval and explicit deferral/extension status may be promoted only after human review.

Workshop suspected-cause statements are stored as source opinions and can never become confirmed cause through the review/promotion path.

The Technical Review Matrix is assembled deterministically from human-approved scalar facts, reviewed repeatable evidence and rule-generated issues. It separates evidence for, counter-evidence, unknown/missing evidence and recommended follow-up; it does not determine causation.

## Rationale
Marine machinery claims often contain repeated maintenance jobs, component findings and alternative repair scopes. Treating these as one scalar value would overwrite evidence and destroy provenance. Keeping them as repeatable evidence preserves source granularity and supports later technical reasoning without converting source opinion into system truth.
