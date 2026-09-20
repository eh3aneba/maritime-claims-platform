# Phase 17.5-AE — service-executor dispatch consumption

Issue: #500

Base: `main@df39fccf808e380e2feeac57a764d5e2f6a40866`

## Outcome

Turn one immutable AD due-tick dispatch into exactly one AC-equivalent metadata-only observation using a non-human internal service identity.

## Core invariants

- no synthetic User;
- one actor class per observation;
- one consumption per dispatch;
- one observation per schedule/due tick across human and service paths;
- no second provider read when human AC already completed the tick;
- no content/storage/Document/Evidence/processing/AI authority.

## Worker

`external_evidence_observation_worker` consumes at most one outstanding dispatch per iteration. Polling is bounded by configuration. The logical service-executor identifier is non-secret and only its normalized SHA-256 hash is persisted.
