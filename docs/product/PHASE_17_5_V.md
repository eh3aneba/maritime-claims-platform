# Phase 17.5-V — Generation-3 successor exact-item observation

## Purpose

Phase V performs one explicit Admin + MFA metadata-only observation of the exact provider file bound to an immutable Phase U generation-3 checkpoint.

It answers only whether that exact item is:

- `unchanged`
- `changed`
- `missing` because the provider returned canonical not-found

It does not ingest a new file body and does not create product evidence authority.

## Eligible lineage

`U checkpoint generation 3 → T candidate generation 3 → S changed observation → R/Q/P/O and original governed source lineage`

The generation-3 metadata baseline comes from the exact Phase S observation consumed by T. V revalidates U/T/S and reconciles T/U byte, MIME and version facts to that baseline before any provider call.

## Execute endpoint

`POST /api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-3-executions/{checkpoint_generation_3_execution_id}/generation-3-successor-change-detection-executions`

Request body:

```json
{
  "request_key": "operator-controlled-idempotency-key",
  "reason": "Reason for this manual exact-item observation."
}
```

All other fields are rejected. The caller cannot choose the provider item ID, endpoint, path, version, generation, cursor, token, content or storage coordinates.

## Read endpoints

- `GET /api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}`
- `GET /api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}/receipts`

Every read revalidates full persisted lineage and fails closed on upstream, execution or receipt drift.

## Allowed authority

On successful completion only:

- transient provider client construction;
- one exact-item metadata read;
- immutable metadata comparison result and receipt persistence.

## Explicitly excluded

Phase V performs no folder listing, file-content read, provider write/delete, object-storage read/write/delete, restaging, checkpoint advancement, Evidence admission, Document creation, parsing/OCR/indexing, Claim mutation, subscription, cursor, polling or recurring/background synchronization.

## Failure behavior

Only canonical provider not-found becomes a successful `missing` observation. Permission/authentication errors, timeout/unavailability, malformed or oversized responses, provider rejection, adapter exceptions and item-identity mismatch fail the request without persisting a successful observation.

## Replay

An exact replay returns the existing completed execution and does not issue a second provider request. A replay that changes actor/reason/checkpoint under the same request key conflicts.

## Next authority decision

After V, a separately reviewed phase may consume only a V `changed` observation to restage a generation-4 candidate. Alternatively, the product sequence may move to separately reviewed human Evidence admission/current `Document` semantics. Recurring/background synchronization remains later.
