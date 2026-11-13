# Private Pilot Security Checklist

## Required before sharing with a design partner

- [ ] `SECRET_KEY` replaced with 32+ random characters.
- [ ] Database password replaced; no `change-me-*` value remains.
- [ ] `.env` is not committed to Git.
- [ ] `CORS_ALLOWED_ORIGINS` contains only expected web origins.
- [ ] External AI remains disabled unless contractual/data-processing approval exists.
- [ ] `ALLOW_EXTERNAL_AI_RESTRICTED=false` unless separately approved.
- [ ] Pilot host is private/VPN-restricted or bound to an approved internal network.
- [ ] TLS is used before any staging/production internet exposure.
- [ ] Evidence storage directory/volume is access-controlled and backed up.
- [ ] `MALWARE_SCAN_ENABLED=true`; ClamAV health passes before the API accepts pilot traffic.
- [ ] ClamAV port `3310` remains internal to the Compose network and is not internet/host published.
- [ ] Clean synthetic upload and isolated EICAR rejection have both been verified.
- [ ] A bounded legacy rescan has completed and every selected record has a visible verdict.
- [ ] Claims Managers can retry scanner-error records but cannot purge bytes.
- [ ] Administrative purge requires an exact quarantine ID, a recorded reason and prior confirmation that no legal/evidentiary hold applies.
- [ ] A database backup is taken before upgrading or restoring pilot data.
- [ ] Demo credentials are changed from examples and shared out-of-band.
- [ ] Only synthetic data is used until data-processing terms and retention rules are agreed.
- [ ] FNOL OCR is local-only, bounded and executed only after a clean ClamAV verdict.
- [ ] Reviewers understand that extracted/classified values are proposals and must be checked before approval.
- [ ] Incoming PDF signature requirements are explicitly classified and recorded against [#894](https://github.com/eh3aneba/maritime-claims-platform/issues/894); operator approval does not infer cryptographic signature validity from successful extraction, OCR, file hashes or text hashes.
- [ ] PDF processing and source-segment API disclosures show `pdf_signature_check_state=not_checked` for PDF extraction; this **does not detect whether the PDF is signed** and is not an authenticity guarantee.
- [ ] If verified signatures are required for incoming evidence, an independently approved verifier, synthetic intact/tampered signature tests, trust-chain policy and fail-closed release criteria are completed before using the claim; otherwise documents remain unverified evidence requiring human examination.
- [ ] Critical Persian H&M OCR negation, date and machinery terms have a separately authorized bilingual source-comparison review; a successful `eng+fas` worker test alone does not establish semantic fidelity ([#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810)).
- [ ] A cross-tenant intake ID returns `404` for read and approval attempts.

## Current MVP limitations

- Local object storage is suitable for a private single-host pilot, not high availability.
- Legacy rescan is operator-triggered and bounded; it is not an automatic repository-wide campaign.
- Legal/evidentiary hold remains an operator check before purge; automated retention-policy enforcement is a later milestone.
- No SSO/SAML, session revocation list or enterprise identity lifecycle yet.
- No formal penetration test has been completed.
- No production-grade secrets manager integration yet.
- Backup automation is baseline/manual; retention and off-host encryption must be configured by the operator.
- OCR is Tesseract-based and does not provide handwriting guarantees or semantic document understanding.
- Poppler cryptographic PDF signature verification is disabled in the SQLite-free Worker build; PDF text/raster extraction, a stored `file_hash` and extracted `text_hash` do not authenticate a signer or the signed revision.

These limitations are acceptable only for a controlled design-partner pilot using synthetic or formally approved data. They are not a claim of production certification.
