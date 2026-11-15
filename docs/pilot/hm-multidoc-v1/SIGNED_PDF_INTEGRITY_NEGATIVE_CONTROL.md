# Fictional signed-PDF cryptographic integrity negative control (#894)

## Observed behavior and reproducible test

The synthetic-only backend test in apps/api/tests/test_signed_pdf_integrity_not_checked.py generates a fresh, ephemeral RSA private key and fictional self-signed X.509 certificate. It constructs a one-page PDF with an AcroForm signature widget, Adobe detached CMS (PKCS#7) signature, ByteRange and Contents, without committing or uploading any PDF, certificate, key or customer data.

On an Ubuntu test runner with the OpenSSL CLI, a test-only detached CMS integrity check using openssl cms -verify -binary -noverify succeeds for the originally signed ranges. A deliberate **same-length source change** substitutes "Engine stable" with "Engine failed" inside the covered page content stream. The PDF remains structurally parseable and carries the original signature widget, but the detached signature no longer verifies over the altered bytes.

Both intact and modified PDFs are independently fed into the actual SeeClaims pypdf text extractor. In each case, text extraction may succeed, while the source bytes and their original SHA-256 remain unchanged by processing. Both responses must report pdf_signature_check_state=not_checked, without a signer verification or signature validity assertion. A successful PDF parse is not evidence that a signed revision remains intact.

**Scope:** The fictional certificate is self-signed and intentionally untrusted. OpenSSL -noverify here checks cryptographic **content integrity only**, not certificate-chain trust, revocation, time-of-signing policy or the claimed signer's identity. The test FAILS CLOSED if the OpenSSL CLI is missing from the controlled runner; an unavailable integrity oracle cannot count as a green acceptance control. This fixture is not a real customer scan or independent signed-PDF evaluation cohort.

## Release and owner decision remain unresolved

The production Worker does not execute this test-only OpenSSL verifier and still builds Poppler without the NSS3/GPGME signature-verification backends. This change implements **no** production signature validation, trust engine or signed-PDF classification policy.

Issue #894 remains OPEN until an authorized product/security owner decides whether signed incoming PDF verification is in Pilot v1 scope. If required, select and validate a supported separately reviewed implementation, including certificate chain, revocation, signature time and document revision manipulation, fail-closed behavior, provenance/SBOM and final-image vulnerability tests across architectures. If excluded, record the scope decision and preserve the unverified status for operators. Independent review and real-customer permission are distinct; Pilot remains NO-GO.
