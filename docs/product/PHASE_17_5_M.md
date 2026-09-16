# Phase 17.5-M — bounded remote file-content read proof

Phase 17.5-M is the first Phase 17.5 tranche allowed to observe remote file bytes.

It is deliberately **not** a synchronization or ingestion feature.

## What M can do

For one integrity-valid Phase L listing, an organization administrator with MFA may select exactly one Phase L metadata item by its **local metadata-item UUID**. The item must already be recorded as a file.

M may then:

- construct the governed transient provider client inside the adapter;
- read that one exact remote file body;
- hold the body only transiently in process memory;
- enforce an 8 MiB body limit;
- compare actual size with Phase L metadata when a declared size exists;
- compare the observed provider version-token hash with Phase L when available;
- compare the bounded media-type class;
- calculate SHA-256 and exact byte count;
- persist only those non-content proof facts and immutable lineage receipts.

## What the request cannot control

The API request contains only:

- `request_key`
- `reason`

The route itself contains local Phase L listing/item UUIDs.

The caller cannot submit:

- provider item IDs;
- provider paths or URLs;
- provider download/export URLs;
- HTTP headers or byte ranges;
- credentials, tokens or client objects;
- file bytes or extracted text.

The provider endpoint is derived internally from the active governed source profile and the exact integrity-valid Phase L item.

## Content-discard rule

Remote bytes exist only while the adapter result is being validated and hashed.

Before Phase M returns a successful execution, the byte-bearing result is discarded. There is no Phase M database field or API field capable of carrying the body.

Phase M persists only:

- `content_sha256`
- `content_byte_count`
- bounded `media_type_class`
- `observed_version_token_hash` where available
- `latency_class`
- exact Phase L listing/item hashes
- requested/completed receipt hashes

The digest is proof that the bytes were observed; it is not a Document, Evidence object or staged content blob.

## Provider-specific boundary

### SharePoint

M derives the exact Microsoft Graph drive-item content operation from the governed site/library profile and persisted Phase L provider item. A protocol-required provider content redirect may occur only inside the adapter under the bounded one-hop HTTPS redirect policy. Redirect URLs and headers never enter application persistence or API output.

### Google Drive

M derives the exact `files.get` media equivalent for the persisted Phase L item. Google-native document export is not authorized in this phase. The Phase M Google Drive policy does not authorize redirects.

## Fail-closed conditions

M refuses execution when, among other cases:

- the Phase L listing or any upstream A→L lineage is no longer integrity-valid;
- the selected item is not a file or does not belong to the exact listing/tenant;
- the credential reference is no longer active;
- the declared Phase L file size exceeds 8 MiB;
- actual bytes exceed 8 MiB;
- actual size differs from recorded Phase L size;
- media type or provider version proof drifts;
- the provider adapter is missing or its provider/client/origin/operation/redirect policy is not approved;
- a provider call fails or returns malformed data.

Failed attempts roll back the requested execution and receipts.

## Still unauthorized after M

Phase M does **not** provide:

- durable remote-content storage/staging;
- local `Document` creation;
- Evidence admission;
- Claim Fact creation;
- synchronization or checkpoint state;
- subscriptions or recurring/background reads;
- archive expansion, OCR, parsing or extracted text;
- remote upload/edit/move/rename/delete;
- claim mutation;
- automated coverage, causation, liability, fraud, reserve or settlement decisions.

## Next authority boundary

The next separately reviewed tranche may introduce durable remote-content staging plus synchronization/checkpointing. Document creation and Evidence admission remain later independent authority increases and must not be inferred from a successful Phase M read proof.