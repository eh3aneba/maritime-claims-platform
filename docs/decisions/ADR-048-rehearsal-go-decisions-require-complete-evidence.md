# ADR-048 — Rehearsal Go decisions require complete evidence

Status: Accepted

A design-partner rehearsal must be anchored to an attested readiness snapshot. Each of the eight controls receives a bounded
reference, human summary and explicit pass/fail/not-tested result. The platform blocks a Go outcome unless all eight results
are pass and every remediation finding is resolved. A Manager/Admin freezes the decision as a canonical SHA-256 snapshot.

This record is a pilot governance aid, not a production certification or automated compliance conclusion. The system stores
no secret value, credential, raw artifact, deployment instruction or claim/message content in rehearsal evidence.
