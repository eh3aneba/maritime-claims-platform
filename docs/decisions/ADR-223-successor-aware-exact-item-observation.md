# ADR-223: Successor-aware exact-item observation

## Status

Accepted for Phase 17.5-S implementation and production-gate validation.

## Context

Phase 17.5-R records an immutable generation-2 successor synchronization checkpoint after one exact Phase P changed observation has been reread and restaged by Phase Q. Phase R deliberately does not perform another provider observation and does not make the original Phase P generation-1 observation endpoint implicitly follow later generations.

A later observation therefore needs an explicit authority boundary that says which checkpoint generation is being observed, where its baseline comes from, and what provider action is permitted.

## Decision

Phase 17.5-S introduces a separate successor-aware exact-item observation execution and receipt chain.

The execution is anchored to one completed, integrity-valid Phase R generation-2 checkpoint. Its baseline is not the original Phase O metadata snapshot. It is the exact Phase P observed projection that Phase Q consumed and Phase R advanced into generation 2, cross-checked against the Q content proof and R successor state.

The persisted lineage is therefore:

`O generation 1 → P changed observation → Q generation-2 candidate → R generation-2 checkpoint → S metadata observation`

Phase S reuses the already-approved Phase P exact-item metadata adapter and provider policy. It does not add a new provider operation class.

## Why the baseline is the Phase P observed projection

Phase O describes generation 1. Once a changed Phase P projection has been reread, staged by Q, and explicitly advanced by R, that changed projection is the metadata state associated with generation 2. Comparing a later provider observation against Phase O would incorrectly compare the provider against stale generation-1 metadata.

Phase S therefore derives generation-2 baseline facts from the immutable Phase P observed projection and proves that Q/R carry the same provider identity, version/content facts where those facts are available.

## Exact-item provider authority

Phase S permits only one bounded metadata request for the lineage-derived exact provider item.

SharePoint uses the governed Graph drive-item metadata endpoint and fixed projection:

`id,name,size,lastModifiedDateTime,file,folder,parentReference,eTag`

Google Drive uses the governed exact file metadata endpoint with `supportsAllDrives=true` and fixed projection:

`id,name,mimeType,size,modifiedTime,parents,md5Checksum`

Existing response-size and timeout bounds remain in force and redirects remain disabled.

The caller cannot provide provider item ID, URL, path, version, generation, cursor, content, storage key or token.

## Classification

A successful exact-item metadata observation is classified as:

- `unchanged` when all bounded comparison dimensions match the generation-2 baseline;
- `changed` when one or more bounded comparison dimensions differ; or
- `missing` only when the provider adapter reports canonical not-found.

Provider identity is an invariant, not a changed dimension. An unexpected provider item identity is a failure.

Authorization failures, permission failures, timeouts, unavailable endpoints, malformed or oversized responses, provider rejection and adapter exceptions remain failures and cannot become `missing`.

If version tokens are absent, the remaining bounded metadata dimensions still provide the comparison. Version-token absence does not suppress changes in byte size, modified time, name, parent, MIME type or item kind.

## Explicit non-authority

Phase S performs no:

- file-body/content read;
- folder or tree listing;
- object-storage HEAD/GET/PUT/COPY/DELETE;
- staging or restaging;
- checkpoint creation or advancement;
- provider write/edit/move/rename/delete;
- subscription, webhook, cursor, polling or background synchronization;
- Document creation or Evidence/Claim Fact admission;
- parsing, OCR, extraction, rendering or indexing;
- Claim mutation or claims decision-making.

DB constraints and immutable receipt hashes encode this boundary.

## Replay and integrity

An exact replay of the same request key, Phase R checkpoint, actor and reason returns the same completed S execution without another provider request. A changed replay conflicts. Separately keyed manual observations against the same generation-2 checkpoint are allowed.

Every execution and receipt read revalidates the full persisted upstream lineage through Phase R. Upstream profile/credential invalidation or O/P/Q/R/S hash/receipt tampering fails closed.

## Consequences

Phase S makes generation-2 change observation explicit without creating a synchronization loop. A later separately reviewed phase may consume an S `changed` result for generation-3 reread/restaging. Human-controlled Evidence admission and current `Document` creation semantics remain a separate authority boundary. Recurring/background synchronization remains later.
