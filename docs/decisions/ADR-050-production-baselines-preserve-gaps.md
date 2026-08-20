# ADR-050 — Production baselines preserve gaps

Status: Accepted

A production-architecture baseline must document all nine required domains with an explicit current state, target design, residual risk, owner and target date. Missing and partial states remain first-class facts: attestation records `attested_with_gaps` instead of promoting them to implemented.

The canonical SHA-256 snapshot always carries `production_certification: false`. Attestation proves only that a Manager/Admin reviewed a complete baseline. It does not deploy infrastructure, verify evidence, assert compliance or authorize production go-live. Material remediation requires a new reviewed baseline rather than mutation of the attested record.
