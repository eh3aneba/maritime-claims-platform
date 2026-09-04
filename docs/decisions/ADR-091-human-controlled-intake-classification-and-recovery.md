# ADR-091 — H&M intake classification remains advisory and processing is recoverable

## Status
Accepted for Phase 13.1 tranche A.

## Context
MCRI already has secure claim intake, malware quarantine, local text extraction/OCR, durable processing jobs and human approval. The intake classifier, however, is deliberately simple and may return `unknown`; the earlier UI could persist that candidate directly as the source document type. Intake processing also had a configured attempt budget but treated every extractor/runtime exception as an immediate terminal failure.

The product direction is feature maturity rather than feature proliferation. This tranche therefore deepens the existing intake capability instead of adding another ingestion or AI surface.

## Decision
1. **Classification is advisory.** `classification_candidate`, confidence and rule explain what the system proposes; they are not authoritative claim data.
2. **Authoritative document type is human-selected.** Approval accepts only a controlled H&M document-type registry. `unknown` is never an approvable type. If the operator cannot map evidence to a specific controlled family, they may explicitly choose `other`.
3. **The same registry drives API and UI.** The web client fetches the server-controlled list and presents localized labels without changing persisted enum-like codes.
4. **Transient intake processing failures retry automatically.** A failed attempt returns to `pending` while the durable attempt budget remains available. The original error is retained and the retry is audit logged.
5. **Known non-reviewable extraction is terminal.** Empty/non-reviewable text does not loop automatically and does not masquerade as successful extraction.
6. **A failed draft can be explicitly reprocessed.** An authenticated tenant-scoped operator action resets the processing attempt budget for that existing draft/job. It never creates a claim, document or fact by itself.
7. **Approval remains idempotent and human-controlled.** No retry, classification proposal or locale action can create authoritative claim truth without the existing approval path.
8. **Security boundaries are unchanged.** File validation, tenancy, malware quarantine and external-AI governance remain server enforced.

## Consequences
- Operators can correct classifier mistakes before persistence.
- `unknown` no longer silently enters the active evidence record as a reviewed document type.
- Temporary extractor/runtime outages can recover without database intervention.
- Terminal failures have an intentional operator recovery path.
- Audit history distinguishes automatic requeue from explicit manual reprocessing.
- Existing downstream document intelligence may rely on a cleaner controlled document-type vocabulary.

## Deferred within Phase 13.1
Canonical structured-fact provenance is a separate subtranche of the **same intake/evidence feature**. The current `ClaimFact` model is tied to an AI `DocumentExtraction`; Phase 13.1 must define first-class lineage for human-approved deterministic/manual intake values without fabricating AI records. This is not a new product feature and must be resolved before Phase 13.1 exits.

## Verification
- backend coverage rejects `unknown`, persists a human correction, verifies transient automatic retry and explicit failed-draft retry;
- browser E2E uploads a real DOCX, observes the advisory classification, changes the authoritative type, creates the claim and verifies the persisted source document through the API;
- existing localization, accessibility, MT ORION and security suites remain required.
