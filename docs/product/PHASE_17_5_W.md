# Phase 17.5-W — Human-controlled external Evidence admission authorization

Phase W is an authorization-only control-plane step between generation-3 exact-item observation and any future local Evidence/Document admission execution.

An Admin with MFA may authorize one exact Phase-V `unchanged` observation for one active Claim in the same tenant. The service revalidates the complete Phase-V integrity chain and confirms that the selected observation is the latest completed observation for its generation-3 checkpoint at the moment of authorization.

The API returns only internal identifiers, hashes, bounded metadata classes and authorization metadata. Raw provider item IDs, URLs, storage keys, credentials, tokens and remote file content are intentionally absent.

## Authority boundary
Phase W does **not** create a `Document`, admit Evidence, parse/OCR/index/extract content, mutate a Claim, construct a provider client, call a provider, access object storage, restage content, advance checkpoints or start synchronization/background work.

The authorization is historical and immutable. If a newer provider observation appears later, the W record remains readable, but a future admission execution must revalidate currentness and reject stale authorization. Future consumption must also be single-use.

## Operator checks
Before authorizing, confirm the Claim is correct and the displayed governed source/version context matches the intended evidence. A failed currentness, integrity or tenant check must be investigated rather than bypassed. Authorization does not mean the file has been admitted into the claim record.
