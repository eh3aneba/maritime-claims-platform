# Phase 17.5-Q — bounded changed-item versioned restaging

Phase Q is a custody step, not synchronization and not Evidence admission.

## What an operator can do

An organization Admin with MFA may take one completed Phase P observation whose result is `changed` and explicitly request a bounded reread/restaging of that exact provider file.

The request body contains only:

- `request_key`
- `reason`

The platform derives the exact provider item, provider endpoint policy, credential reference and storage target from persisted governed lineage. The operator cannot provide a provider URL, item ID, path, version, token, content body, byte range or storage key.

## What happens

1. A deterministic `requested` recovery anchor is committed.
2. The exact changed file is reread under the existing bounded SharePoint/Google Drive content policy.
3. Available Phase P metadata facts are reconciled. Version, size or MIME drift fails closed.
4. SHA-256 and byte count are recorded as a bounded content proof and the `content_verified` state is committed.
5. The body is conditionally written to a new generation-2 quarantine object.
6. That exact object is verified by HEAD/GET and the execution becomes `completed / staged_candidate_verified`.

A crash after object creation is recoverable because the content proof was committed before the storage write. Replay checks the same deterministic candidate object and does not need delete or overwrite authority.

## What remains unchanged

Phase Q does **not**:

- change the Phase O generation-1 checkpoint;
- replace or delete the original Phase N quarantine object;
- mark the new generation as the active synchronized version;
- create a `Document`;
- admit Evidence or create Claim Facts;
- parse, OCR, extract, render or index the file;
- enqueue document processing;
- change a Claim;
- start polling, webhooks, subscriptions or background synchronization.

## Eligibility

Only a Phase P execution with `result_status=changed` can be consumed. `unchanged` and `missing` observations are rejected without a Phase Q provider reread or candidate storage write.

One Phase P changed observation can produce at most one Phase Q candidate. Exact replay is idempotent. A changed replay or second consumption conflicts.

## Candidate generation

The candidate is generation `2` in Phase Q custody terminology. This does not mean the Phase O checkpoint has generation 2. Checkpoint advancement is intentionally reserved for a later separately reviewed authority increase.

## Failure behavior

Provider authentication/authorization errors, timeout, malformed result, oversized content, version mismatch, byte-size mismatch, MIME mismatch, object-store integrity failure or upstream lineage invalidation all fail closed.

No such failure is converted into a successful restaging event.

## Audit and secrecy

APIs and audit records may include bounded hashes, lineage IDs, generation number, content SHA-256/size, result state and safety facts. They must not contain provider secret values, tokens, raw provider response bodies, file bodies, provider download URLs, raw storage keys or signed storage URLs.

## Next authority boundaries

After Q is proven and merged, separately review:

1. controlled checkpoint-generation advancement to an exact integrity-valid Phase Q candidate;
2. human-controlled Evidence admission and the platform's existing `Document` semantics;
3. only then recurring/background incremental synchronization.
