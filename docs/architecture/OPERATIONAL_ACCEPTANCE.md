# Operational Acceptance & Bounded Go-Live Authorization

## Purpose

Sprint 10E records whether named humans authorize a specific release for a specific production change window. It consumes a completed nine-control verification snapshot but does not reinterpret or replace that evidence. It never runs deployment commands, changes infrastructure, enables traffic, certifies production or activates an external AI provider.

## Preconditions and checks

Only a completed `architecture_v2` gate may anchor an attempt. Historical `foundational_v1` gates remain valid evidence for their original scope but cannot authorize this stage.

Every attempt freezes exactly seven bounded checks:

1. release artifact
2. migration plan
3. backup and restore
4. observability and alerting
5. incident response
6. rollback rehearsal
7. support coverage

Each check stores pass/fail, an accountable owner, an allowlisted `artifact://`, `runbook://`, `ticket://` or `monitor://` reference, and a concise human note. Raw artifacts, URLs, secrets, credentials and claim content are excluded.

## Independent decision lifecycle

1. A Manager/Admin requests an attempt and supplies a future timezone-aware window no longer than 24 hours and no more than 90 days away.
2. A different Manager/Admin issues the Operations decision.
3. A second different Manager/Admin issues the Risk decision.
4. Approval is blocked unless all seven checks pass; either reviewer can reject the attempt.
5. Only an Admin different from the requester may record Authorize or Hold after both approvals.
6. Authorize expires at the window end. Reject/Hold permits a new append-only attempt; every terminal attempt is immutable.

The canonical SHA-256 snapshot includes release/window identity, owners, checks, reviewer identities and references, final outcome, and explicit false action flags. Authorization is a decision record only: deployment and traffic enablement remain separate operational actions. External AI activation follows the independent roadmap in `docs/product/AI_ACTIVATION_ROADMAP.md`.
