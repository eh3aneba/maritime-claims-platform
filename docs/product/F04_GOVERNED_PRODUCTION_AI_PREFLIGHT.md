# F04 — Governed production AI preflight

## Problem

The generic deployment preflight still carried the historical Sprint 11A rule that OpenAI was allowed only in staging. That contradicted the later governed Production AI control planes and made a correctly governed Production deployment fail before runtime authorization could be evaluated.

## Deployment capability

`AI_PRODUCTION_CONTROL_PLANE_ENABLED=true` is now required when `APP_ENV=production` and `AI_PROVIDER=openai`.

This setting is a deployment capability declaration only. It does not authorize any organization, claim, document, user, model run, rollout cohort or provider call.

## Runtime authority remains separate

Production AI still relies on the existing database-backed governance chain and its queue-time / worker-time checks. Runtime authorization, bundle pinning, document eligibility, human review, monitoring, incidents, expiry, kill-switch state and other control-plane restrictions remain authoritative.

Therefore:

- provider configuration alone is insufficient;
- the production capability flag alone is insufficient;
- a live runtime authorization is still required for each governed path;
- Restricted external-AI processing remains disabled;
- staging continues to use its staging authorization path.

## Fail-closed behavior

- Production OpenAI with the capability flag missing/false fails preflight.
- Production OpenAI with the capability flag true is no longer rejected solely because the environment is Production.
- Development/pilot environments cannot enable OpenAI through this flag.
- Normal model/key/bundle/input/output checks continue to apply.

## Validation

`test_production_deployment_policy.py` covers the missing capability, governed Production capability, and staging compatibility cases. Full repository CI, production-policy, security, performance and browser E2E gates remain required before merge consideration.

## Merge boundary

No merge without fresh explicit user authorization.
