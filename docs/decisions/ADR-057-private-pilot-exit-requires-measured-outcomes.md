# ADR-057: Private-pilot exit requires measured outcomes and independent review

## Status

Accepted for Sprint 11D.

## Decision

Completing a bounded real-document private pilot does not demonstrate that the workflow is useful, safe, affordable or ready for wider evaluation. A separate append-only outcome assessment must cover every reviewed run and pass the fixed `private_pilot_exit_v1` thresholds before a positive exit recommendation can be considered.

The assessment reads human actions, latency and observed provider cost from the immutable Sprint 11C run ledger. It adds one content-free usability observation per run, separate workflow scorecards, cost and incident trends, deterministic failure reasons and a canonical SHA-256 snapshot. Product, Quality and Risk reviews must be performed by three distinct non-requesting users.

An Administrator may recommend a separately authorized limited-production evaluation, require a new bounded pilot attempt or stop progression. None of these outcomes is a production authorization.

## Consequences

- Pilot completion alone cannot justify scope expansion.
- Missing workflow coverage, missing observations, safety-boundary failures, unresolved/Critical incidents, privacy/security/cross-tenant incidents or failed usability/latency/cost thresholds freeze the attempt as failed.
- Clients cannot relax the server-owned sample and threshold profile.
- The outcome ledger contains aggregate operational evidence and hashes, not claim or provider content.
- Production, Restricted documents and autonomous claim decisions remain prohibited until a separate future authorization is designed, reviewed and explicitly approved.
