# ADR-073 — Production-wide AI remains human-reviewed and scope-frozen

## Status
Accepted for Sprint 11T.

## Context
Sprint 11S can recommend a separate Production-wide authorization review after bounded-100% technical, business and enterprise evidence passes. Production-wide scale must not be confused with autonomous claims authority or broader document scope.

## Decision
Sprint 11T may authorize Production-wide AI only for the exact Chief Engineer Report / Engine Log scope, Internal/Confidential documents, tenant boundary and model/prompt/schema bundle already validated upstream.

Fifteen independent reviewers plus a separate final Admin are required. Authorization expires after at most 90 days and renewal requires a new authorization review.

Per-document rollout attestation is replaced by a deterministic Production Eligibility Policy. Every run receives an immutable eligibility decision and a permanent content-free AI Decision Log entry.

Different-human review remains mandatory. Restricted documents, new document classes, autonomous coverage/liability/causation/reserve/settlement/payment/recovery decisions and automatic authoritative claim-fact updates remain prohibited.

Any Sprint 11T attempt becomes the newest fail-closed control plane. No fallback to Sprint 11R or older authorization is permitted once 11T exists.

## Consequence
Sprint 11T ends percentage-based rollout governance. Subsequent product work should focus on Claims Intelligence capabilities rather than additional rollout-percent stages.
