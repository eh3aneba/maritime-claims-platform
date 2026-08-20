# Limited-Production AI Evaluation

Sprint 11E provides a separately authorized, expiring control plane for evaluating the exact Sprint 11D-recommended AI bundle in Production. It is a small operational experiment, not a Production-wide authorization.

## Authorization chain

1. The anchor must be a completed Sprint 11C pilot with a passing, positively recommended Sprint 11D outcome assessment.
2. A Manager creates an append-only attempt for the exact model, prompt, schema and input/output limits inherited from that anchor.
3. Security, Privacy, Product and Operations approve the bounded controls. The four reviewers must be different people and none may be the requester.
4. An Administrator records the final authorize-or-hold decision. The canonical decision snapshot and SHA-256 hash preserve the exact approvals, bundle, window, cohort, references and limits.

Configuration, deployment and a Sprint 11D recommendation are each insufficient on their own.

## Fixed operating envelope

- Production environment and `limited_production_evaluation` mode only
- Chief Engineer Reports and Engine Logs only
- non-Restricted, current, tenant-owned documents only
- deterministic document bucketing with a declared rollout from 1% through 10%
- maximum 10 claims, 30 documents, 10 users and 100 provider runs
- maximum 14-day authorization window
- fixed 15-minute rollback SLO and 60-minute monitor interval
- 100% different-human review before downstream use
- maximum 20% Reject, 50% Edit, 30-second P95 latency and 500,000 micro-USD mean observed provider cost

Each document also needs current legal-basis, data-minimization and change-control references. The ledger stores identifiers, measurements, bounded references and hashes; it does not store document content, prompts, provider responses, candidates, secrets or calculated billing.

## Runtime enforcement

The queue gate and worker gate both verify the active authorization, tenant, pinned bundle, document type, input limit, confidentiality, deterministic rollout bucket, document eligibility, user/run caps, incident state and monitor freshness. A configuration mismatch, expiry, revoked document, open incident, breached cap or stale monitor fails closed.

Only queue-time admission reserves a content-free provider-run record. The worker repeats authorization immediately before provider execution so a pause, revoke or expiry affects jobs already waiting in the queue.

## Monitoring and recovery

A live monitor derives human-review coverage, Reject/Edit rates, latency, observed cost and incident state from immutable run outcomes. A failed threshold pauses the authorization and marks rollback required. Reporting any incident also pauses execution immediately.

An Administrator may resolve an incident, but resolution never resumes execution in the same request. Operators must record a fresh passing monitor after remediation, then an Administrator may explicitly resume. Revocation is an immediate kill switch. Completion requires at least one run, review of every run, no open incident and a fresh passing monitor.

## Preserved prohibitions

Sprint 11E does not authorize Production-wide traffic, rollout above the recorded percentage, Restricted documents, unlisted document types, autonomous claim decisions, automatic authoritative-fact updates or bypass of human review. Completion does not grant any of those capabilities; a later decision must remain separate.
