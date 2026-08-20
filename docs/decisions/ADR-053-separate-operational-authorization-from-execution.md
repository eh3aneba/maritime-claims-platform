# ADR-053 — Separate operational authorization from execution

Status: Accepted

A completed nine-control verification gate demonstrates retained, independently reviewed control evidence. It does not identify a release, change window or accountable operators and therefore cannot itself authorize production use.

Sprint 10E introduces an append-only operational acceptance attempt anchored only to `architecture_v2`. The attempt freezes seven operational checks, four named ownership roles and a bounded change window. Operations and Risk approvals require different Manager/Admin users, both different from the requester. An Admin then records Authorize or Hold in a canonical SHA-256 snapshot.

The decision deliberately has no deployment or traffic side effect and expires at the window end. Its summary explicitly keeps production certification and external-AI authorization false. This separation prevents a technical evidence snapshot from silently becoming change approval, prevents a single actor from requesting and approving a release, and keeps external-AI data processing subject to its own activation and evaluation decision.
