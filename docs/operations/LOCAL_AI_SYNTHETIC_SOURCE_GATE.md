# #752 — local AI source-custody gate (synthetic CI only)

**Status: test contract, not a production local-model adapter.**

The first owner-operated Qwen3 1.7B trial demonstrated 100% GPU
loading on a GTX 1050 personal computer but generated unsourced
"allegations", made unsupported negligence inferences, and sometimes
confused "not supplied" with "never existed". A five-section interactive
benchmark was not valid because the scenario/asks were entered as
separate turns. These are **open quality blockers** for H&M workflow
acceptance, not grounds to assume every local model always fails.

## CI safety boundary

The pure standard-library
`scripts/pilot_local_ai_source_gate.py` checks a *narrow* candidate
output of **literal source excerpts only**. It is runnable with
`python -m unittest discover -s scripts/tests -p 'test_pilot_local_ai_source_gate.py' -v`.

The source inventory must be supplied by an independently authorized
upstream component, for example:

```json
{
  "S1": {
    "kind": "event_notice",
    "version": "v1",
    "body": "Owner notification: Turbocharger damage reportedly occurred on 16 July 2025."
  },
  "S2": {
    "kind": "reported_statement",
    "version": "v1",
    "body": "Chief Engineer reported abnormal vibration before shutdown."
  },
  "S3": {
    "kind": "intake_status",
    "version": "v1",
    "body": "Engine logs for the previous ten days have NOT BEEN SUPPLIED."
  }
}
```

A synthetically generated candidate has this **exact** top-level shape:

```json
{
  "schema": "seeclaims-local-ai-source-quotes-v1",
  "model_id": "qwen3:1.7b",
  "model_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "prompt_version": "synthetic-v1",
  "items": [{
    "kind": "reported_statement",
    "source_id": "S2",
    "source_version": "v1",
    "verbatim_excerpt": "Chief Engineer reported abnormal vibration before shutdown."
  }]
}
```

Every quote must be an **exact substring** of the corresponding
authorized versioned source. A candidate cannot invent an
`allegations`, `coverage`, `liability`, `thinking`,
`interpretation` or other free-text output field. Source kind
(`event_notice`, `reported_statement`, `intake_status`) cannot be
reclassified by the model. All failures use fixed privacy-safe error
codes; the return object contains only bounded metadata and always says
`human_review_required=True`,
`authoritative_fact_updates=False`, `pilot_accepted=False`.

## GitHub-only synthetic Ollama quote-handoff experiment (PR #758)

The added pure `scripts/pilot_local_ai_synthetic_handoff.py` wires
a **hard-coded three-source invented H&M turbocharger scenario** into
the development-only `AIProvider` adapter and the existing source-quote
gate. Its one-shot prompt requests a bounded JSON-only list of literal
source quotes, preserving `event_notice` versus
`reported_statement` versus `intake_status`. It requires the
existing Ollama adapter's synthetic-only metadata and rejects any
other adapter/model identity, unsupported quote, wrong source/version,
extra generated narration or empty items. The only returned result is
bounded evaluation status and a count; it cannot write to a real claim,
document store, database or human approval table.

`apps/api/tests/test_local_ai_synthetic_handoff.py` exercises the
**entire handoff with a mocked transport** to the real Ollama gateway
class, plus wrong-response, invented negligence, fabricated party
allegation and 'not supplied means never existed' negative tests.
The always-on Production Deployment Policy script checks the new
boundary independently without installing or running Ollama.

The mock demonstrates successful local request formation and
source-quote postprocessing, but **does not execute a real local model**,
independently verify an actual model SHA, prove semantic truth,
show safe deployment network policies, and is not a human approval.
The source validation is substring-only, so a verified excerpt
may still mislead a human if taken out of context.

The candidate metadata contains a conspicuous all-zero digest placeholder
used only to satisfy the existing **syntax** schema. This is not a model
artifact attestation and must never authorize a customer model.
The experimental `ollama_local` path remains forbidden outside
development/test, and normal case jobs cannot pass the exact marker.
No new API route, configurable input path, document job consumer, external
provider, customer data or production AI enablement is added.

**Pilot GO remains NO.** The next slice will need real trusted
model-digest custody, separate user/tenant authorization for future
real data, evidence-level schema validation, human review persistence
and independently measured source-accuracy tests before R5 acceptance.

## Hash-only pending review receipt (next synthetic CI slice)

`scripts/pilot_local_ai_synthetic_review_receipt.py` can now consume
the prior **hard-coded invented** H&M source→mocked Ollama→quote validation
handoff and produce a deterministic **hash-only pending review receipt**.
The receipt records a SHA256 of the fixed source catalog, the exact
request, the JSON candidate, plus a content-derived receipt fingerprint,
prompt/schema versions, an *unverified* model tag and verified quote
count. It contains **no actual Evidence, generated narrative or
personally identifiable customer data**.

Receipt status is `pending_unassigned_human_review`; it has
`reviewer_id=null`, `review_decision=null`,
`stored_in_database=false`, `model_digest_attested=false`,
`authoritative_claim_changes=false`, and `pilot_accepted=false`.
This is deliberately **not persisted** and is **not a digital
signature**, model attestation or a human approval. It establishes
reproducible synthetic evaluation identities only. The receipt is
not an accepted Claims Intelligence decision, and **no actual human reviewer**
or sign-off was involved. Any failed source quote prevents receipt creation.

`apps/api/tests/test_local_ai_synthetic_review_receipt.py` verifies
determinism, changes when a valid excerpt changes, privacy-safe
rejection of fabricated negligence and missing-record claims, wrong
provider, malformed/oversized responses and a full **mocked**
Ollama `HTTPConnection` request. The Production Deployment Policy
test separately guards the absence of real-source loaders, persistence
and claimed approval.

Next, create an explicitly authorized, tenant-scoped human-review
handoff and actual append-only custody *after* this static fixture
prototype has passed CI. That future workflow must independently
verify real source permissions, artifact digest, prompt/model identity,
human decision authority and test quality on pre-agreed synthetic
reference answers. This receipt is not evidence of any of those gates.
**Pilot GO remains NO.**

## Read-only synthetic receipt verification before review (PR #761)

`scripts/pilot_local_ai_synthetic_review_verify.py` provides an
**exact-shape, read-only synthetic receipt verification** step after the
hash-only fixture receipt in #759. It recalculates the expected hash for
the **code-owned source catalog and request**, validates quote count,
model/prompt/schema tag and the unmodified canonical receipt hash,
and fails closed if any field falsely asserts approval, a reviewer,
database persistence, model-digest attestation or customer/pilot
authorization.

On success, it returns a **sanitized review preview only**: digest and
quote count, `pending_unassigned_human_review`, and explicit
`reviewer_authorized=false`, `human_decision_recorded=false`,
`may_auto_approve=false`, `persisted_to_review_queue=false`,
`pilot_accepted=false`. This is not an authenticated human-review transition, not a queue insert and not a replacement for the
existing tenant-scoped `DocumentExtraction`/`AIFeedback` authorization
rules and append-only human feedback semantics.

Critically, an **unkeyed hash is not an authenticity signature**.
An attacker who can edit the candidate hash and recompute the receipt
hash may forge consistent strings. The verifier deliberately returns
no approval authority even after verification. Model artifact identity
is also not attested; source quote semantics can remain misleading.
This limitation has its own regression test. The same reviewer
authorization, genuine Evidence custody and human decision gates
remain necessary before this can be integrated into the actual
claim-intelligence workflow.

**Pilot GO remains NO.** Only invented data and mocked provider
responses are used for this development stage.

## What remains UNSOLVED

- This gate **does not invoke Ollama**, load a real model, establish model
  digest authenticity, verify the upstream source inventory, trace page
  locations in PDFs, make factual inference, or verify semantic meaning.
  It checks exact source-byte grounding and caller-assigned source type
  only. Even an exact quote may be cherry-picked or misleading.
- Model metadata is **self-reported by the candidate**; upstream must
  independently pin/compare model/version/prompt before production
  authority. The gate never logs full Evidence or model free text.
- Hypotheses and unknowns must be represented in a **separate,
  explicitly unverified human-review structure**, not laundered through
  an accepted source quote as fact or party allegation.
- The synthetic development-only evaluator now calls the quote gate, but no real claim AI job is wired to it. A future implementation PR
  must place it behind the provider-neutral job, source-document
  authorization and tenant boundary before calling an actual local
  model. AI still must not set coverage, settlement, liability, reserve
  or promoted claim facts.
- Neither success here nor the owner's personal-PC benchmark establishes
  a production deployment, data isolation, egress prevention,
  external-provider compatibility or R5 pilot acceptance.

**Next engineering slice:** inventory current AI gateway and current
review/feedback persistence; add a local model adapter with loopback /
deny-by-default transport, immutable run metadata and synthetic
request/timeout/oversize tests. Keep `ai_provider=disabled` until
a separate operationally approved candidate is proven.
