# ADR-051 — Production control evidence requires independent review

Status: Accepted

Implementation evidence for identity/access, evidence storage, observability, backup/DR and deployment/IaC is stored as versioned submissions anchored to an attested architecture baseline. The submitter cannot verify their own evidence. A different Manager/Admin must reproduce the stated method and either verify it with a bounded review reference or reject it with a written reason.

Rejected versions remain immutable; correction creates a new version. A canonical SHA-256 snapshot is available only when the latest version of all five controls is independently verified. The snapshot always records `production_certification: false`, `go_live_authorization: false` and `content_or_secrets_included: false`; it is evidence governance, not automated deployment or approval.
