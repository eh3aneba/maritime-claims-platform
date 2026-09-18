# F06 — Canonical Production AI runtime selector

## Problem

Production intelligence enqueue paths already use `app.modules.ai_runtime`, which selects the newest applicable governed Production AI control plane and fails closed when a newer control plane exists but is inactive.

The processing worker was still importing the older `ai_governance` facade directly. In Production that legacy facade routes to Sprint 11E limited-production authorization, creating a queue-time / worker-time authority mismatch.

## Fix

The worker now imports `require_external_ai_runtime_authorization` from `app.modules.ai_runtime`, exactly like the intelligence enqueue path.

No Production authorization logic is duplicated in the worker. The canonical selector remains responsible for the ordered control-plane lineage:

11T → 11R → 11P → 11N → 11K → 11I → 11G → 11E.

If a newer control-plane attempt exists, its inactive or non-executable state fails closed instead of silently falling back to an older stage.

## Regression contract

A focused architecture regression asserts that both:

- queue-time intelligence authorization; and
- worker-time provider authorization

reference the exact same canonical selector function from `ai_runtime`.

Existing Sprint-specific tests continue to prove no-fallback semantics for newer control planes such as 11T and 11R.

## Boundary

This change does not broaden:
- allowed document classes;
- confidentiality levels;
- rollout percentages;
- provider quotas;
- monitoring or incident controls;
- human-review requirements;
- autonomous claim authority.

It only removes divergence between queue-time and worker-time authorization selection.

## Merge control

No merge without fresh explicit user authorization.
