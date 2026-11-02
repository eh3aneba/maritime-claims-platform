# Codex Cloud setup for SeeClaims (synthetic development only)

This is a **setup guide**, not evidence of a connected or accepted Codex
environment. A human must authorize the GitHub connection and publish the
cloud environment. Do not connect an insurance customer evidence store.

## Before connecting

- Choose the GitHub repository `eh3aneba/maritime-claims-platform`.
- Verify it is the correct repository and that the intended branch is visible.
- The repository-level [AGENTS.md](../../AGENTS.md) is for Codex instruction
  discovery; it does **not** enforce GitHub permissions or security policy.
  GitHub rules and human reviewers remain the actual merge controls.
- Use a disposable setup environment; no production DB, claim files, credentials
  or real policyholder data. Do not put live secrets in setup commands or logs.

## Suggested cloud environment

1. Open [Codex](https://chatgpt.com/codex), select Cloud work and create a
   development environment connected to the repository above. UI labels may
   differ by client; use the current official Codex environment instructions.
2. Configure Python 3.13, Node.js 22 and access to an isolated PostgreSQL
   service for tests requiring a database. A working Docker/Compose runtime
   cannot be assumed; inspect available cloud features before enabling them.
3. Install reproducibly from `apps/api/requirements-dev.lock` and
   `apps/web/package-lock.json` (use `npm ci`). No unreviewed upgrades.
4. Set `AI_PROVIDER=disabled`; disable external inference and external
   evidence connectors; restrict outbound traffic where supported. Never
   import customer Evidence into the cloud workspace.
5. For the first environment check, run safe commands such as:
   - `python -m unittest scripts.tests.test_backend_shard_selector -v`
   - `cd apps/web && npm ci && npm run typecheck && npm run build`
   - `cd apps/api && python -m compileall app alembic`
   Backend API tests requiring PostgreSQL or ClamAV are run only after
   installing/starting the corresponding isolated test services.
6. Record what actually passed, what was skipped and the exact base SHA.
   Publishing an environment or passing a synthetic test is **not Pilot GO**.

## First Codex task: measure CI bottlenecks, do not rewrite them blindly

> On the current default branch of
> `eh3aneba/maritime-claims-platform`, inspect
> `.github/workflows/backend-premerge.yml`,
> `.github/workflows/ci.yml`,
> `.github/workflows/postgres-concurrency-regressions.yml` and
> `.github/workflows/performance-smoke.yml`.
> Read the scoped CI classifier tests and issue #553. Use available,
> dated GitHub run/job evidence to measure queue time, setup time, test time
> and wall-clock critical path on several recent successful PRs.
> Identify bottlenecks and propose exactly one fail-closed CI improvement,
> with a regression test and an objective before/after measurement method.
> Keep all existing required check names and branch protections.
> **Do not** edit workflows, change branch rules, merge or deploy during
> this first diagnostic task. Use synthetic-only inputs; report the evidence
> sources, head SHA, tradeoffs and unresolved assumptions.

After reviewing the diagnosis, assign one bounded implementation task to
Codex. Work on a branch/PR, inspect the diff, run targeted tests, and wait
for exact-head protected GitHub checks before authorizing a merge.

## Local/GPU alternative

For tests that require the owner's local Ollama GPU runner, use an appropriately
installed local Codex client from the checked-out project and avoid cloud
transfer of any real claims. A local `qwen3:1.7b` synthetic demo is not proof
of acceptable source attribution or independent H&M expert quality.

## Success measure

Compare **PR lead time**, **test queue vs execution time**, **first-pass CI
success rate**, and **accepted H&M workflow outcomes** before and after the
agent workflow. Number of commits/PRs alone is not a useful success measure.
