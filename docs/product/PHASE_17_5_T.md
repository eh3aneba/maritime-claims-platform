# Phase 17.5-T — Bounded successor changed-item generation-3 restaging

## Operator summary

Phase T handles one exact Phase S observation that is already classified `changed` against the immutable generation-2 successor checkpoint.

An organization Admin with MFA may explicitly request one bounded reread of that same exact file. If the reread reconciles with the Phase S observed metadata facts, the body is placed into a new immutable quarantine candidate generation 3.

## What Phase T does

- revalidates the complete persisted source lineage;
- accepts only an exact completed Phase S `changed` observation;
- derives the provider file target from persisted lineage;
- performs one bounded exact file-content reread using the existing governed content-read policy;
- reconciles byte size, MIME class and version token when Phase S observed values are present;
- commits a content proof before object-store write;
- writes one deterministic generation-3 object with put-if-absent semantics;
- verifies the object by hash and byte count;
- records requested/content_verified/completed receipt hashes.

## Recovery behavior

If the process stops after the generation-3 object was written but before completion was committed, exact replay does not blindly reread or rewrite.

The service first checks the deterministic object. If that object exactly matches the committed content proof, the execution completes from that object without another provider reread or PUT. If the object is missing, the provider may be reread and the result must exactly match the previously committed proof before storage is attempted again.

There is no delete or overwrite recovery authority.

## What Phase T does not do

Phase T does not:

- list or discover remote folders/items;
- mutate the generation-2 checkpoint;
- mutate the generation-2 candidate/object;
- change the Phase S observation;
- create or advance a generation-3 checkpoint;
- create a `Document`;
- admit Evidence or Claim Facts;
- parse, OCR, render, index or extract content;
- enqueue document processing;
- start recurring/background synchronization;
- write/edit/move/rename/delete provider files;
- mutate a Claim or make claim decisions.

## Eligibility

`changed` is eligible.

`unchanged` and `missing` are not eligible for Phase T and fail before file-content or object-storage I/O.

A Phase S observation may be consumed successfully only once. Exact replay with the same request key, actor and reason is idempotent. A changed replay or second separately keyed consumption conflicts.

## Candidate generation

The new candidate is fixed to generation `3`. The raw internal storage key is custody-only and is never returned by the API or audit payload; only its hash is exposed.

## Next authority boundary

A later separately reviewed phase may advance an immutable generation-3 checkpoint from one exact completed Phase T candidate.

Human-controlled Evidence admission/current `Document` creation remains separate. Recurring/background synchronization remains later.
