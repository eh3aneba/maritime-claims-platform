# ADR-114 — Repeatable performance smoke and provisional SLO baseline

## Status
Accepted as the Phase 14.2 design under #205. The implementation is not part of `main` until its pull request passes the exact-head verification gate and receives fresh explicit merge authorization.

## Context
Phase 14.1 established privacy-safe request correlation and dependency-aware liveness/readiness. It deliberately did not choose Prometheus, OpenTelemetry, Sentry or another telemetry vendor, and it did not define load benchmarks or operational SLO thresholds.

Before selecting telemetry infrastructure, the platform needs a small repeatable measurement contract that can run against the same real Docker design-partner stack already used for governed MT ORION acceptance. The first purpose is regression detection and comparability, not production capacity certification.

## Decision

### 1. Phase 14.2 adds a bounded live-stack performance smoke
A dependency-free Python harness runs against the real isolated Docker stack and measures three deliberately bounded read paths:

1. `api_liveness` — process-only `/api/v1/health/live`;
2. `database_readiness` — PostgreSQL-backed `/api/v1/health/ready`; and
3. `authenticated_claim_list` — authenticated claim-list retrieval against the seeded design-partner tenant.

The harness authenticates through the existing human login API, retains the returned bearer token in memory only, and then performs a small configurable number of warmup and concurrent sample requests.

The JSON artifact records only:
- scenario label;
- sample/success/failure counts;
- bounded status-code counts;
- error ratio;
- p50/p95/p99/max request latency;
- observed throughput; and
- whether the broad CI budget passed.

It does not record request or response bodies, credentials, bearer tokens, cookies, claim identifiers, external references, claim text, evidence content, correspondence, legal analysis or insurance analysis.

### 2. CI budgets are regression tripwires, not production SLO evidence
The initial GitHub-hosted-runner budgets are intentionally broad:

| Scenario | CI p95 budget | CI error ratio |
| --- | ---: | ---: |
| API liveness | <= 1000 ms | 0% |
| Database readiness | <= 1500 ms | 0% |
| Authenticated claim list | <= 2500 ms | 0% |

Default execution uses 3 warmup requests, 24 measured requests per scenario and concurrency 4.

These numbers answer only: **did this exact change create an obvious operational regression in the controlled CI stack?** They must not be described as contractual performance commitments, production capacity limits, or proof of a production service-level objective.

GitHub-hosted runners have variable CPU, I/O and network scheduling. Tight percentile budgets in that environment would create false confidence when green and false alarms when noisy.

### 3. Provisional production objectives remain measurement hypotheses
Until sustained deployment telemetry exists, production SLOs remain provisional hypotheses rather than enforced promises. The initial measurement questions are:

- service availability: can the required API/database dependencies serve valid traffic consistently over a meaningful window?;
- interactive read latency: what p50/p95/p99 latency do normal claim-workspace reads show under real operator use?;
- error budget: what proportion of valid requests fail for platform reasons rather than user validation/authorization outcomes?; and
- saturation: at what concurrency do database/API/frontend resources show a material latency or failure inflection?

Phase 14.2 does **not** assign a contractual availability percentage or a production p95 promise. A later tranche may turn measured deployment evidence into explicit SLI/SLO policy.

### 4. Vendor selection remains deferred
The new performance artifact is plain JSON and the harness uses only the Python standard library. This preserves the option to later feed equivalent measurements into Prometheus/OpenTelemetry/Sentry or another platform without making Phase 14.2 dependent on a telemetry vendor.

Distributed tracing, long-duration soak/stress tests, autoscaling policy, production alert routing and telemetry retention are outside this tranche.

### 5. Performance measurement must not become a claims-data side channel
Operational performance tooling is infrastructure tooling, not a second claim store.

The harness may know a seeded search value in memory so that it exercises a representative authenticated route, but the persisted artifact uses only the safe scenario label `authenticated_claim_list`. The tested query, credentials, token and response payload are not persisted.

No performance result creates or changes coverage, causation, fault, liability, fraud, recoverability, governing-law, time-bar, reserve, settlement, payment or claim-closure authority.

## Verification gate
The Phase 14.2 pull request is merge-ready only when, on the exact pull-request head:
- Operational Performance Smoke passes the bounded live-stack budgets;
- backend full suite is green;
- PostgreSQL migration/preflight is green;
- frontend typecheck/build is green;
- dependency-lock and Docker Compose validation are green;
- full MT ORION browser acceptance is green;
- Supply Chain Security is green;
- there are no unresolved review blockers;
- the branch is not behind `main`; and
- fresh explicit user authorization has been given for the Phase 14.2 PR.

Refs #205
Refs #202
Refs #25
