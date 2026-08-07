# ADR-024 — Design-partner deployment uses explicit go/no-go gates

## Status
Accepted

## Context
A claims platform can pass unit/integration tests yet fail on a fresh workstation because of migrations, build-time frontend configuration, missing secrets, browser/API connectivity or environment-specific dependency issues.

## Decision
A design-partner walkthrough is permitted only after three explicit host-level gates pass: fresh Docker build/startup, Next.js production build, and browser E2E against the seeded MT ORION environment. Repository-level tests are necessary but not a substitute for these gates.

The compose stack runs database migrations and application preflight as one-shot services before API/worker startup. The web service waits for API health.

## Consequences
- No one may label a build design-partner ready solely because backend tests pass.
- Host-specific failures are discovered before the walkthrough rather than during it.
- The current execution environment may produce a conditional readiness result when Docker/npm are unavailable; that limitation must be stated rather than inferred away.
