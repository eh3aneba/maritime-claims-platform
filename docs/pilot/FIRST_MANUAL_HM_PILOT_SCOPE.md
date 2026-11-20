# First H&M machinery pilot — manual-only, synthetic rehearsal scope (v1.1)

**Selection:** a deliberately smaller, safer FIRST rehearsal within [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647); tracks operational evidence under [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653).

**Current release decision: NO-GO for customer evidence.** This authorizes no data transfer, new tenant, procurement, deployment or coverage determination. One named insurer/team and independent release/security/H&M reviewers have not been accepted in the repository. First prove a clean, independently controlled isolated host using the existing **fictional MT ORION** documents. Do not replace this with a developer laptop's green CI or a customer tenant seed.

## In scope now

- One **H&M machinery** handling team at one insurer. First walkthrough: one fictional case (MT ORION); extending to the later 5–10/30-day design-partner study is a separate authorization and measured milestone.
- **Authenticated manual upload only**. Preserve original bytes, versions, SHA-256, quarantine/ClamAV and a human source/original review. Native document text may be displayed for reference but must never be represented as independently verified.
- Human handler reviews missing/contradictory evidence, chronology, technical and financial material, versioned Initial Assessment and correspondence/Claim Pack output. No automated coverage, liability, causation, reserve, settlement, payment or claim closure.
- AI **OFF** (both external OpenAI and unaccepted local Ollama); no AI-model inference, no automatic approval or AI-derived machine facts. The first scope also turns **all OCR OFF**, including Persian Tesseract, to avoid exposing handlers to the independently reproduced missing-negation defect. Image-only/scanned documents therefore require a direct original-source manual read; no OCR quality or semantic accuracy is claimed.

## Enforced configuration at startup of the existing Compose path

The selected first pilot uses `.env.pilot.example` with private replacement secrets and `APP_ENV=pilot`. The **preflight** of the deployment dependency chain rejects any nonempty AI model/key, non-disabled AI provider, enabled local/production AI controls, enabled live external-provider/SFTP adapter, or `OCR_ENABLED=true`. The **pre-Docker synthetic-demo guard** rejects the same expanded scope before it can build, migrate, or seed MT ORION. The worker reads the `OCR_ENABLED=false` switch explicitly.

These bounded tests are a **configuration/startup gate**, not a firewall, actual-network-egress test, tenant-count enforcement, proof that third-party connectors cannot be enabled via other software, or approval of a human's decision. On a selected host, independently inspect the rendered private Compose config and **actual running service environment** with the existing sanitized scope readback; verify scanner, storage, network/TLS/firewall isolation and exact image digests. Stop if flags or host/runtime differ. Never print `.env`, `docker compose config` or credentials to public CI/issues.

SFTP, SharePoint/Drive/email ingestion, external API access, local/external AI experiments, automatic Persian negation extraction, other insurance lines, a public API and multi-tenant rollouts are **out of scope**. SFTP acceptance [#652](https://github.com/eh3aneba/maritime-claims-platform/issues/652) is therefore **not a prerequisite for this disabled-SFTP scope**, but must pass independently before any later SFTP enablement. Do not claim the mere presence of an external-evidence worker means an actual remote connector is enabled.

## Signed incoming PDF

Original PDF bytes and checksums are retained. Evidence UI and exported Claim Pack PDF/XLSX say **INCOMING PDF SIGNATURES NOT CHECKED**. Extraction or hashing does NOT authenticate signer, signed revision or certificate trust. An accountable product/security owner must **approve in writing** whether the first pilot excludes signed originals altogether or permits them for **manual, explicitly unverified** use. Before that disposition [#894](https://github.com/eh3aneba/maritime-claims-platform/issues/894), do not admit real signed claim evidence. Do not claim that this scope check implements a signature verifier.

## No-GO prerequisites: who must supply the actual evidence

| Owner | Minimum independently observed result |
| --- | --- |
| Selected-host deployment operator | Clean/isolated host; one exact signed-off main SHA and approved immutable API/Web/Worker/Postgres/ClamAV images; safe secrets, MFA, ClamAV, migrations, all 11 service readiness checks and a real handler completing the fictional journey |
| Backup/custody operator + independent verifier | Quiesced **matching PostgreSQL and Evidence** off-host recovery point; new isolated restore; hash/row/audit/receipt reconciliation; measured recovery; controlled rollback to known-good image with compatible migrations |
| Monitoring/on-call operator | Real delivered and acknowledged alerts for API/DB/worker/scanner/storage/backup freshness/restore; recorded escalation and failure response |
| Independent security owner | Private per-finding review of eight historical [#764](https://github.com/eh3aneba/maritime-claims-platform/issues/764) Gitleaks matches, revocation/rotation where relevant, passing scheduled-equivalent **full-history** scan; reconciled Alpine/OpenSSL/source-built OCR component provenance [#952](https://github.com/eh3aneba/maritime-claims-platform/issues/952) without CVE waivers |
| Independent bilingual H&M reviewer | Confirm original-source review protocol, including negation/date/machinery and discrepancy follow-up. OCR remains out of scope until unbiased evaluation [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810)/[#850](https://github.com/eh3aneba/maritime-claims-platform/issues/850) |
| Product/release/tenant owner | Dated signed-PDF scope decision, authorized synthetic data class and confidentiality, reviewed one-tenant onboarding method **not demo-seed**, retention/offboarding, formal release/no-release approval |

**Release candidate:** complete the v5 private gate under `scripts/pilot_rc_gate.py` with actual evidence references, exact image digests, flags `sftp_ingestion=disabled`, `ai_inference=disabled`, `persian_critical_extraction=disabled`. A string `pass`, a green GitHub run, or a mock operator is *not* independent acceptance. The existing guard deliberately does not declare Pilot GO.

**Only after all gates above pass** may the accountable team ask for a separate, approved **real-data** pilot authorization. Until then, all work uses synthetic fixtures on an approved isolated environment. Do not use production credentials, a customer scan, external AI, an unknown Docker Engine or unreviewed SFTP endpoints.
