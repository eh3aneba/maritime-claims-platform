# ADR-039: Versioned human-reviewed adjustment statements

- Status: Accepted
- Date: 2026-08-14

## Context

The Financial Review holds source-linked invoice lines, quotation alternatives,
review statuses, deterministic flags and reserve history. A professional claim
adjustment needs explicit line treatments, PA/GA and other allocation bases,
deductibles, credits and written reasoning. Those decisions can affect indemnity
and must not be inferred by the platform.

## Decision

Create currency-specific, versioned adjustment statements from current invoice
Cost Items only. Copy source values into immutable line snapshots and require a
human to choose every treatment and basis.

Only Claims Managers/Admins may approve. Approval freezes the statement with a
deterministic content hash. Quotation alternatives, FX conversion, reserve
updates, settlement and payment authorization remain outside the calculation.

## Consequences

- Claims teams gain an auditable adjustment schedule without turning review cues
  into automated recoverability decisions.
- Approved versions remain stable if source Cost Items later change.
- New evidence requires a new statement version.
- Payment approval and settlement execution require separate controls.
