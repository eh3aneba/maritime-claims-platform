# ADR-026 — Standalone Processes Must Explicitly Bootstrap Database and ORM Context

## Status
Accepted

## Context
FastAPI request handlers receive a bound database session through dependency injection. CLI tools and background workers do not. Fresh-process validation revealed that direct `SessionLocal()` use could create unbound sessions, and a standalone worker could start without importing enough model modules to resolve ORM relationships.

## Decision
- All non-request processes obtain database sessions through `create_session()`, which explicitly binds the configured engine.
- Standalone workers import the central ORM metadata registry before querying ORM models.
- Fresh-process behavior is covered by deployment-readiness regression tests.

## Consequences
This makes CLI tools, seeders, preflight checks, and workers behave consistently when launched independently from the FastAPI application process. It also reduces reliance on incidental router import order.
