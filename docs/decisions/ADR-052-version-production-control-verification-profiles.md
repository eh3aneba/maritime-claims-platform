# ADR-052 — Version production-control verification profiles

Status: Accepted

Sprint 10D extends implementation evidence and independent verification to application security, data governance, interoperability and AI governance, completing the nine-domain production architecture set.

The required set is stored as an immutable profile on each gate. Existing Sprint 10C gates become `foundational_v1` and keep identity/access, evidence storage, observability, backup/DR and deployment/IaC. New gates use `architecture_v2` and require all nine architecture controls. Evidence outside a gate's profile is rejected.

This version boundary prevents a completed historical gate from becoming apparently incomplete, changing status semantics or being re-hashed after the required scope grows. The v2 canonical snapshot records its profile. Both profiles retain versioned submissions, independent Manager/Admin review, bounded references, append-only rejection history and the explicit false production-certification and go-live-authorization flags.

Operational acceptance and traffic enablement remain a separate, explicitly authorized decision. A completed nine-control verification gate is necessary evidence for that later decision, not the decision itself.
