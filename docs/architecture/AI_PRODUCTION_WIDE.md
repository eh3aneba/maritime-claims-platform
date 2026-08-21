# AI Production-wide Human-reviewed Control Plane

Sprint 11T is the final Production AI authorization layer. It may authorize Production-wide execution only for the exact Chief Engineer Report and Engine Log workflows already measured through Sprint 11S.

## Entry chain
One immutable Sprint 11S assessment must be `recommended` with outcome `recommend_separate_production_wide_authorization_review` and `metrics.overall_pass=true`. The Sprint 11S assessment/decision hashes and linked Sprint 11R decision/completion hashes are frozen into the 11T authorization.

## Eligibility policy
Production-wide does not require manual per-document rollout attestation. Every runtime request is evaluated by a deterministic Production Eligibility Policy using tenant, document type, confidentiality, legal-basis policy, data-minimization policy, exact model/prompt/schema bundle and current authorization state. The policy and each decision have immutable SHA-256 hashes. Raw document text is not stored in this control ledger.

## Scope
Allowed document classes remain `chief_engineer_report` and `engine_log`; confidentiality remains Internal/Confidential only. Restricted documents and new document classes are not authorized.

## AI Decision Log
Every Production-wide run creates a permanent content-free AI Decision Log entry with authorization hash, eligibility policy/decision hashes, claim/document/workflow identifiers, requester/reviewer, model/prompt/schema bundle, human action, candidate/edit/unsupported/grounding metrics, latency, provider cost, run hash and review hash. Raw prompts and provider responses are excluded from the governance ledger.

## Runtime precedence
11T is the newest Production control plane. Once any 11T attempt exists for a tenant, inactive/pending/held/rejected/paused/revoked/expired state fails closed and cannot fall back to 11R or earlier controls.

## Change governance
Any change to model, prompt bundle, schema bundle, input/output limits or equivalent provider configuration causes runtime bundle mismatch and requires a fresh authorization/change review.

## Human boundary
Different-human review remains mandatory. Sprint 11T does not authorize autonomous coverage, liability, causation, reserve, settlement, payment or recovery decisions, nor automatic authoritative claim-fact updates.
