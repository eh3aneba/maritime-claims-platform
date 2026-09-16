# Phase 17.5-S — Successor-aware exact-item observation

## Operator purpose

Phase 17.5-S lets an authorized Admin with MFA manually check the exact provider item represented by an immutable Phase R generation-2 successor checkpoint.

This is a metadata observation, not a synchronization run.

## What S observes

S derives the exact provider target from persisted lineage. The operator supplies only:

- a request key; and
- a reason.

The generation-2 baseline comes from the metadata projection that Phase P observed as changed and that Phase Q/R subsequently accepted as generation 2. S does not compare against the older Phase O generation-1 baseline.

## Results

A completed observation reports one of:

- `unchanged` — bounded exact-item metadata still matches generation 2;
- `changed` — at least one bounded metadata dimension changed; or
- `missing` — the exact item returned canonical provider not-found.

Other provider failures remain failures. A permission problem, timeout, malformed response or provider rejection must not be interpreted as deletion.

## Compared dimensions

S compares:

- item kind;
- display name;
- parent item identity;
- MIME type class;
- byte size;
- modified time; and
- version-token hash when available.

The exact provider item identity itself must never change. An identity mismatch fails the execution.

When no version token is available, S continues comparing the other bounded dimensions.

## What S does not do

S does not:

- download or read the file body;
- relist a folder or discover other items;
- read or write object storage;
- stage/restage a new generation;
- create or advance a checkpoint;
- create a `Document`;
- admit Evidence or Claim Facts;
- run OCR, parsing, extraction or indexing;
- mutate a Claim;
- create a subscription, webhook or background polling loop;
- write, move, rename or delete provider content.

## Replay behavior

Repeating the exact same completed request key, checkpoint, actor and reason returns the existing execution without another provider metadata call. Changing the request under the same key conflicts.

Different request keys may be used for later manual metadata observations of the same generation-2 checkpoint.

## Integrity behavior

Before provider access, S revalidates the complete persisted lineage through the Phase R successor checkpoint. Later reads revalidate the same lineage and S's own immutable request/completion/receipt hashes.

Tampered upstream records, invalidated credentials or profile state, or altered S receipts fail closed.

## Next authority boundary

A future separately reviewed phase may consume an S `changed` result to reread and stage generation 3. Evidence admission and `Document` creation remain separately human-controlled. Recurring/background synchronization remains later.
