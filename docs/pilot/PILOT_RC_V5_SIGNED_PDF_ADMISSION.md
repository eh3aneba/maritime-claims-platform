# Pilot v1 release candidate v5 — incoming signed-PDF evidence admission (#894)

**Status: fail-closed structural gate; NO product/security approval recorded; customer Pilot remains NO-GO.**

The [signed-PDF scope issue #894](https://github.com/eh3aneba/maritime-claims-platform/issues/894) and [release-readiness #653](https://github.com/eh3aneba/maritime-claims-platform/issues/653) require an explicit accountable disposition of *already-signed PDF inputs*. This is distinct from building a service that creates electronic signatures. The existing production extractor uses pypdf and optional OCR; the Worker has Poppler NSS3/GPGME cryptographic-signature backends disabled to keep its final image SQLite-free. Successful parsing, unchanged uploaded-file SHA-256, `pdf_signature_check_state=not_checked`, and synthetic OpenSSL `-noverify` integrity tests **do not establish trusted signer identity, intact signed revision, certificate chain, revocation or signing-time validity**.

## Change in release-record contract

`scripts/pilot_rc_gate.py` creates only `mcri-pilot-rc-v5` release drafts. It adds the **unconditional** `proofs.signed_pdf_inbound_scope_security_disposition` entry. As with all unconditional proofs, the structural validator requires `result=pass`, a nonblank private evidence reference, an accountable owner and a canonical UTC observation timestamp; unset, failed or `not_applicable` values fail closed. The proof remains mandatory even when local AI, Persian critical extraction and SFTP ingestion are all disabled.

**Old v1/v2/v3/v4 drafts are deliberately rejected**, not silently upgraded or relabeled. Prepare a new private v5 draft, reconcile the exact SHA, image digests and every existing proof from current evidence, and never copy a previous `pass` uncritically.

```bash
python -m scripts.pilot_rc_gate init --output /secure/pilot-releases/rc-v5.json --release-sha "$(git rev-parse HEAD)"
python -m scripts.pilot_rc_gate check /secure/pilot-releases/rc-v5.json --expected-sha "$(git rev-parse HEAD)"
```

A structural PASS only establishes that fields were provided in the correct shape. It **cannot** independently verify the decision, reviewer qualifications, signed evidence, actual deployed policy or cryptographic test findings. No customer documents, credentials, certificate keys, approval workpapers or names of private reviewers should be posted to GitHub.

## Independent owner/security decision: one of two documented branches

### A — Verification required for incoming signed PDFs

Before setting the proof to `pass`, an authorized product/security owner must approve the exact verification and operator-display contract. Independently review a supported isolated verifier or carefully justified alternative that does **not** reintroduce High-severity vulnerable SQLite/NSS into final images. Evidence should cover intact, post-sign modified, multiple revisions, multiple signatures, trust-chain policy, expiration/revocation/time-of-signing policy where applicable, malformed/unsupported files, no false success on parsing/OCR, fail-closed behavior, original-byte provenance, SBOM, both architecture scans, final-image Grype High and current full exact-head CI. Record an independent dated security review.

**Until such implementation and review actually pass, this branch cannot supply the required proof.** The existing fictional self-signed OpenSSL `-noverify` negative control is NOT sufficient.

### B — Signature verification expressly excluded from Pilot v1

The authorized product/security owner must explicitly approve that incoming PDF evidence will **not** receive cryptographic signature verification in this bounded Pilot v1, and document whether pre-signed PDF inputs are allowed for ordinary *unverified* handling or disallowed entirely. If allowed unverified, operators must see `not_checked` and must not be led to believe hashes, signatures, OCR or signer authenticity were validated. If disallowed, there must be **observed admission/configuration enforcement** in the chosen pilot runtime; documentation alone is not a block. Record the contractual/customer limitation, applicable handling controls, a separate independent human security/product review, and a dated restricted evidence reference.

**Until the scoped exclusion is signed and independently checked, the proof remains pending.** Do not treat this guide, a green synthetic CI run or an issue closure as authorization.

## Downstream Claim Pack export disclosure — warning, not verification

The Claim Pack **PDF and XLSX** exports display an explicit notice that SeeClaims
does **not cryptographically verify incoming source-PDF signatures**, the
signed revision or signer identity. Text extraction/OCR and SHA-256 hashes do
not establish PDF-signature authenticity. The notice applies even when the
underlying claim has no PDF: it describes a **missing verification capability**,
not a claim that a signature was found, was valid, or was tampered with.
The same warning is visible in the claim-handler Evidence screen.

This protects downstream human recipients from treating a generated pack as
signed-original verification. It does **not** enforce a ban on incoming signed
PDFs, add a cryptographic verifier, decide the allowed pilot scope, replace
original evidence, or satisfy the independent product/security approval required
by Issue #894. The unconditional RC v5 disposition remains pending until
actual independently reviewed evidence is recorded.

## Separate release gates are never waived

Historical secret disposition [#764](https://github.com/eh3aneba/maritime-claims-platform/issues/764), bilingual original-scan OCR reliability [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810) when in scope, source discrepancy resolution [#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850), and full chosen-host/recovery/operator acceptance [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653) remain independent. No application signature validation or trust implementation is introduced by the v5 record gate. No real customer deployment or Pilot GO is implied.
