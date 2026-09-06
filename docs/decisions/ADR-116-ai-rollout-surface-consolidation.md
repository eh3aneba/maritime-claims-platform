# ADR-116 — Historical AI rollout stages are retired into canonical operator surfaces

## Status
Accepted as the Phase 14.4 design under #210. The implementation is not part of `main` until its pull request passes the exact-head verification gate and receives fresh explicit merge authorization.

## Context
The platform accumulated a sequence of operator-visible AI rollout and readiness pages while external-AI use was being expanded through bounded cohorts. Those pages documented real governance stages, but the stage names became first-class product navigation alongside the durable AI operator capabilities.

Phase 14 explicitly requires consolidation or retirement of historical AI rollout/readiness surfaces that duplicate product intent. The product now has stable surfaces for human review, governance, evaluation, operations and integrations. Keeping every former rollout milestone in primary navigation makes the application harder to understand and risks implying that historical rollout phases are independent current authorities.

This decision is a product-surface consolidation. It does not erase governance history, evaluation evidence, authorization records, audit data or existing backend controls.

## Decision

### 1. Five AI surfaces remain canonical
The durable operator-facing AI product surfaces are:

- **AI Review** (`/ai-review`) — human review of AI-derived proposals and evidence-linked outputs under existing authority boundaries;
- **AI Governance** (`/ai-governance`) — governed authorization/control state;
- **AI Evaluation** (`/ai-evaluation`) — evaluation evidence, outcomes and readiness interpretation;
- **AI Operations** (`/ai-operations`) — operational rollout state, health and controlled operational actions; and
- **AI Integrations** (`/ai-integrations`) — governed integration configuration and status.

Only these AI surfaces remain in the authenticated primary navigation.

### 2. Historical rollout stages redirect to AI Operations
The following historical production/rollout routes become backward-compatible redirects to `/ai-operations`:

- `/ai-private-pilot`
- `/ai-limited-production`
- `/ai-scale-up`
- `/ai-broader-production`
- `/ai-high-coverage`
- `/ai-final-production`
- `/ai-near-universal-production`
- `/ai-bounded-full-production`
- `/ai-production-wide`

These paths represented rollout progression rather than separate durable product domains.

### 3. Historical outcome/readiness stages redirect to AI Evaluation
The following historical outcome/readiness routes become backward-compatible redirects to `/ai-evaluation`:

- `/ai-pilot-outcomes`
- `/ai-limited-production-outcomes`
- `/ai-scale-up-outcomes`
- `/ai-broader-production-outcomes`
- `/ai-high-coverage-outcomes`
- `/ai-final-production-readiness`
- `/ai-final-production-outcomes`
- `/ai-near-universal-outcomes`
- `/ai-bounded-full-production-outcomes`

These paths represented evaluation/readiness gates and therefore resolve to the durable evaluation surface.

### 4. Retirement is staged and reversible
Phase 14.4 uses non-permanent Next.js redirects. The historical page source files remain in the repository during the first retirement period rather than being deleted in the same tranche.

This gives three benefits:

1. existing bookmarks and internal references do not become 404s;
2. the product can consolidate immediately without deleting historical implementation context; and
3. rollback remains low-risk if a legacy dependency is discovered.

Physical deletion of unreachable legacy page source is separate code-debt cleanup and should happen only after the redirect period demonstrates that no active workflow depends on those pages.

### 5. Navigation/redirects have zero mutation authority
Opening a historical URL or navigating among the canonical AI surfaces must not itself execute AI, approve/reject evidence, change governance state, change rollout state, mutate integration configuration or perform any claim-domain write.

Browser acceptance therefore observes API traffic and fails if the consolidation journey emits POST, PATCH, PUT or DELETE requests.

### 6. Data and authority are unchanged
This tranche does not:

- change database schemas or migrations;
- delete or rewrite governance/evaluation records;
- expand external AI provider access;
- change evidence confidentiality rules;
- change model/provider authorization;
- create automated coverage, causation, fault, liability, fraud, recoverability, governing-law, legal time-bar effect, reserve, settlement, payment or claim-closure authority; or
- change canonical Claim Facts, Recovery/Time-Bar, Initial Assessment, Correspondence or Claim Pack boundaries.

## Verification gate
The Phase 14.4 pull request is merge-ready only when, on the exact pull-request head:

- frontend typecheck/build passes;
- backend full suite passes;
- PostgreSQL migration/preflight passes;
- Docker Compose and dependency-lock checks pass;
- the real design-partner browser stack confirms canonical navigation and every retirement redirect with zero mutation requests;
- the existing MT ORION operator journey remains green;
- Operational Performance Smoke passes;
- Supply Chain Security passes;
- the branch is not behind `main`;
- there are no unresolved review blockers; and
- fresh explicit user authorization has been given for the Phase 14.4 PR.

Refs #210
Refs #202
