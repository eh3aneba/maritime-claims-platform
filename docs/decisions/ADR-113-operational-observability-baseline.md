# ADR-113 — Operational observability baseline

## Status
Accepted as the Phase 14.1 design under #203. The implementation is not part of `main` until its pull request passes the exact-head verification gate and receives fresh explicit merge authorization.

## Context
Phase 13 completed the core H&M claims-domain maturity gate. ADR-112 explicitly left infrastructure observability, load/performance testing and operational SLOs as post-Phase-13 hardening.

The first operational audit found that the API exposed only `/api/v1/health`, which always returned `status=ok`, while Docker used that same shallow endpoint as the API container healthcheck. The main FastAPI application also had no explicit request-correlation layer for joining an operator/client report to one request-level operational record.

Phase 14.1 establishes the minimum dependency-aware and privacy-safe baseline before choosing metrics, tracing, load tooling or SLO thresholds.

## Decision

### 1. Request IDs are operational metadata, not claim data
Every handled HTTP response carries `X-Request-ID`.

A caller-provided request ID is preserved only when it matches a deliberately narrow safe character/length policy. Missing or unsafe values are replaced with a generated opaque UUID-derived ID. The effective ID is also placed on `request.state` for later server-side correlation.

The request completion event contains only:
- event name;
- request ID;
- HTTP method;
- URL path;
- status code; and
- elapsed milliseconds.

The middleware must not log request bodies, authorization/cookie headers, correspondence text, evidence content, document payloads, claim facts or legal/insurance analysis.

Unhandled request exceptions emit only the same bounded failure metadata. Exception messages and tracebacks are deliberately excluded from this operational request logger because they can embed claim, evidence, credential or dependency details. Any future diagnostic exception sink must be separately designed, access-controlled and privacy-reviewed.

### 2. Liveness and readiness have different meanings
`/api/v1/health/live` is a cheap process liveness check. It must not make external dependency calls.

`/api/v1/health/ready` is a dependency-aware readiness check. Phase 14.1 verifies the PostgreSQL connection using a minimal `SELECT 1` through the existing production engine/session path.

If the database probe fails, readiness returns HTTP 503 with a bounded `database=unavailable` signal. It must not expose database URLs, credentials, driver errors or connection exception text.

The existing `/api/v1/health` route remains available for backward compatibility and retains cheap process-health semantics. Runtime orchestrators must use `/health/ready` when deciding whether the API is ready to serve dependent application traffic.

### 3. Startup preflight and runtime readiness are complementary
The existing preflight remains responsible for startup configuration/environment checks and migration/schema readiness. Runtime readiness does not replace preflight; it detects loss of a required dependency after startup.

Docker therefore changes only the API runtime healthcheck target from `/api/v1/health` to `/api/v1/health/ready`.

### 4. Vendor observability tooling is deliberately deferred
Phase 14.1 does not select Prometheus, OpenTelemetry, Sentry or another telemetry vendor. It also does not define worker-heartbeat persistence, distributed traces, alert thresholds, load benchmarks or operational SLO targets.

Those decisions should be made after the baseline request/dependency semantics are stable and measurable.

## Authority and privacy boundary
This is platform operational telemetry only. It creates no automated coverage, causation, fault, liability, recoverability, governing-law, time-bar, reserve, settlement, payment or claim-closure authority.

Operational telemetry must remain metadata-minimal and must not become a second storage path for claim evidence or privileged/confidential content.

## Verification gate
The Phase 14.1 pull request is merge-ready only when:
- backend full suite is green;
- the new request-ID/logging and readiness success/failure regression tests are green;
- PostgreSQL migration/preflight remains green even though no migration is added;
- Docker Compose validation is green with the readiness healthcheck;
- frontend build/typecheck remains green;
- Supply Chain Security is green;
- branch is not behind `main` and there are no unresolved review blockers; and
- fresh explicit merge authorization is given for that exact PR.

Refs #203
Refs #202
