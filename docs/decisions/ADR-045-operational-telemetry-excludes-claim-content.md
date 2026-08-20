# ADR-045 — Operational telemetry excludes claim content

Status: Accepted

Operational monitoring stores bounded counts and deterministic alert metadata only. Claim facts, document text,
email/portal bodies, participant data and credential references remain in their governed source modules and are not copied
into monitor runs. Human-owned incidents hold operational summaries, not raw evidence.
