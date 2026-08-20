# Private Pilot Execution Baseline

## Purpose

The private-pilot ledger bridges a completed design-partner rehearsal and later production engineering. It records whether the human workflow was usable, where time was spent and which product gaps require ownership. It is not a claim-decision engine or a production-readiness certificate.

## Lifecycle

1. Create a draft only from a completed rehearsal whose decision is Go.
2. A Manager/Admin explicitly starts the execution.
3. Handlers record bounded case-run measurements and product gaps.
4. Owners accept, resolve or reject gaps with a written note.
5. A Manager/Admin freezes Proceed, Pause or Stop. Proceed requires every P0 gap to be resolved.

## Data boundary

Case runs may store a claim identifier, result, four duration values, AI-review counts, deterministic-rule counts, open conflict/requirement counts and an allowlisted external evidence reference. Aggregate metrics set `content_included` to false. Claim narrative, document text, correspondence, personal data, secrets and external credentials are outside this model.

Approved-real mode is exceptional: it requires an approved pilot-governance profile and a bounded `artifact://`, `runbook://`, `ticket://` or `monitor://` authorization reference. The application stores the reference, not the authorization artifact or secret.

## Outcome integrity

The outcome hash covers the execution identity, rehearsal, data mode, human note, aggregate metrics and the priority/category/status of each product gap. Completed executions reject further case-run or gap mutation. Every state change is tenant scoped and audit logged.
