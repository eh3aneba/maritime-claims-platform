# SeeClaims agent instructions

SeeClaims is a marine insurance claims platform. The first customer-facing
objective is one **H&M machinery claims** handler workflow, not more product
surface area. Read `README.md` and consult
`docs/roadmap/SEECLAIMS_V1_EXECUTION_STATUS.md` for scope or release decisions;
read only the documentation relevant to a small code change.

## Safety and insurance-domain invariants

- Preserve organization/tenant isolation, role checks, evidence access
  authorization, source document versions and content hashes, immutable audit
  trails, and approved historical ClaimFacts/assessments.
- No AI or OCR result may automatically determine coverage, causation,
  liability, reserves, settlement or payment. Human review remains authoritative.
- Machine extraction is **unverified** until separately assessed. An OCR
  discrepancy report or independent workpaper observation does not clear the
  original source hold. Critical Persian negation/source fidelity remains an
  open quality gate (issues #810 and #850).
- Never send customer files, claim text, personally identifiable evidence,
  API keys or production secrets to cloud coding agents or external AI services.
  Use invented synthetic fixtures only. Real-claim pilot release remains NO-GO.
- Pilot v1 uses authenticated manual evidence intake. Keep SFTP, email,
  Drive and external inference OFF unless separately authorized and tested.
  Do not silently enable external services or weaken fail-closed controls.

## Coding workflow

- Inspect the exact issue, nearby implementation, and existing regression tests
  before editing. Prefer one coherent, bounded change with tests to broad
  refactors or extra features. Do not alter unrelated subsystems.
- Backend: `apps/api/` (FastAPI, SQLAlchemy, Alembic). Frontend:
  `apps/web/` (Next.js, React, TypeScript). Keep business decisions in backend.
- Preserve documented API contracts, database migration lineage, decimal
  financial values and timezone semantics. Add regression tests for security,
  wrong-tenant access, stale source/approval state and retries when relevant.
- Use locked dependencies, not opportunistic upgrades. Do not edit generated
  lockfiles except as part of an explicitly scoped dependency task.
- If a task involves deployment or release, consult
  `docs/roadmap/SEECLAIMS_V1_EXECUTION_STATUS.md` and issue #653 first.
  Do not infer host, secret, backup/restore or pilot approval from green CI.

## Validation

- Use the smallest meaningful **local** checks first. Examples:
  - Backend: `cd apps/api && python -m pytest -q tests/<relevant_test>.py`
  - Frontend: `cd apps/web && npm run typecheck && npm run build`
  - Repo policy scripts: `python -m unittest scripts.tests.<relevant_module> -v`
- Tests requiring PostgreSQL, ClamAV, Docker or Ollama need the corresponding
  isolated test services. Never describe an unrun test as passing.
- Follow the committed GitHub workflows for complete PR validation. Preserve
  existing 11 required check contexts and exact-HEAD gates; don't weaken
  branch rules, bypass failures, publish false green statuses or skip mandatory
  tests for production backend changes.
- CI uses scoped synthetic checks for qualifying changes but production/shared/
  ambiguous backend changes require full matrix validation; do not classify
  them as narrow merely to save time.

## Handoff / pull-request policy

- Create a PR rather than pushing straight to `main`. Keep one principal
  implementation package active and avoid speculative PR chains.
- Report changed files, tests actually run, results, unverified assumptions,
  open risks, exact head SHA and any human/host acceptance blockers.
- Never merge, deploy or upload customer evidence without the product owner's
  explicit authorization in that task. GitHub controls and human approval are
  separate from agent output.
