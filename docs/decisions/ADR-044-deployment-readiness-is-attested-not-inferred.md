# ADR-044 — Deployment readiness is attested, not inferred

Status: Accepted

The application records an explicit eight-control snapshot, deterministic hash and Manager/Admin attestation.
It will not infer production readiness from application health or successful CI alone. A failed control blocks attestation,
and an attestation represents only the captured pilot environment snapshot.
