# Main branch required gate matrix

## Current protection

Repository ruleset `Protect main` (ruleset ID `20842512`) is active on the default branch with:

- deletion protection;
- non-fast-forward protection;
- squash-only pull-request merges;
- required review-thread resolution;
- strict/up-to-date required status checks;
- required linear history;
- no bypass actors.

The active required status checks are currently:

- `Backend tests`
- `PostgreSQL migration chain`
- `Frontend typecheck and build`
- `Docker Compose validation`

That matrix is narrower than the repository's actual production-quality validation surface.

## Workflow availability on main

At the stabilization baseline represented by this PR, the workflow definitions needed to emit the target contexts below are present on `main`, including the specialized PostgreSQL safety workflows introduced by A03 and A02.

This satisfies the workflow-availability prerequisite for expanding the required-gate matrix. It does **not** mean the expanded ruleset is enforced. Ruleset mutation, readback of the expanded matrix, and deliberate failure proof remain separate administrative steps.

## Target required status checks

### Core CI

- `Backend tests`
- `PostgreSQL migration chain`
- `Frontend typecheck and build`
- `Docker Compose validation`
- `Dependency lock consistency`
- `Design partner browser E2E`

### Security, deployment and operations

- `Secret history scan`
- `Production dependency audit and SBOM`
- `Container image vulnerability scan`
- `Production environment policy`
- `Live-stack performance smoke`

### Specialized PostgreSQL safety gates

- `Processing lease fencing` — introduced by A03;
- `Payment settlement concurrency` — introduced by A02.

## Safe activation sequence

1. Confirm every target context is emitted successfully from the workflow definitions now present on `main` and on a fresh pull request.
2. Update `Protect main` using an authorized GitHub administration surface.
3. Preserve:
   - strict/up-to-date required checks;
   - squash-only merge policy;
   - review-thread resolution;
   - linear history;
   - empty bypass actor set.
4. Read back the ruleset and compare the exact required context names with this document.
5. Create a temporary validation PR that intentionally fails one required critical gate.
6. Confirm repository protection marks the PR non-mergeable without bypass.
7. Restore the check, rerun it, and confirm mergeability returns.

## Important failure mode

Do not require a status context before a workflow capable of producing that context exists on the default branch. GitHub can otherwise leave every pull request permanently waiting for a check that can never be reported.

## Governance rule for new workflows

Any new workflow that protects one of the following must be explicitly reviewed for required-gate treatment:

- financial authority or concurrency;
- authentication or MFA;
- tenant isolation;
- evidence integrity or processing leases;
- Production AI authorization;
- supply-chain security;
- deployment policy;
- disaster recovery or data-loss prevention.

If a specialized workflow should not become a separate required context, its critical assertion must be aggregated into an already-required stable gate and documented.

## Enforcement status

This document describes the target protection matrix. It does not by itself change GitHub branch protection.

Do not claim the expanded matrix is enforced until a ruleset readback shows the exact contexts above and a deliberate failure test proves protection blocks merge.
