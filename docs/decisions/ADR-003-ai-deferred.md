# ADR-003: Defer AI processing until the claim/document foundation exists

Status: Accepted

## Decision
Sprint 2 contains no OCR, LLM, RAG, embeddings, or predictive models.

## Rationale
AI must sit on top of a secure source-of-truth, review workflow, tenant model, and document lifecycle rather than becoming the system of record itself.
