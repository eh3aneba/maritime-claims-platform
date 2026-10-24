# Experimental local Ollama adapter — Issue #752

**Status:** implemented **development-only**, mock-transport CI tested,
**not deployed or pilot-authorized; mock-transport CI tested,** with
operator-supplied real localhost **synthetic-only** timing observations.
A short artificial 2-request timing probe measured 9,096ms reported load on
its first request versus 8ms on the second with `keep_alive="1m"`. This is
operator-provided data, not a verified H&M throughput benchmark.
The primary source-of-truth for the roadmap remains R0/R5 and issue #752.

## Why this slice is deliberately narrow

SeeClaims already has `app.ai.gateway.AIProvider`, source-linked
Chief Engineer / Engine Log schemas, durable `ai_runs`, review queue and
existing OpenAI adapter. The owner's first `qwen3:1.7b` GPU-only smoke
demonstrated local hardware feasibility but the interactive H&M case output
invented party allegations and sometimes inferred maintenance negligence.
A local adapter alone is **not** a cure for those semantic errors.

This PR supplies an `OllamaLocalExperimentalProvider` in
`apps/api/app/ai/gateway/ollama_local.py` that implements the existing
`generate(AIRequest)->AIResponse` shape using Python stdlib
`http.client.HTTPConnection`. Its endpoint is the **literal** IPv4
loopback `127.0.0.1:11434`, HTTP `POST /api/generate` with exact
structured JSON schema, `stream=false`, `think=false`, and deterministic
temperature. It does not resolve DNS, consult OS proxies, interpolate a
remote URL, follow redirects, set credentials, or invoke any external
inference provider. The fixed HTTP read timeout is **30 seconds** only for this synthetic-only
localhost experiment (the prior 10-second bound rejected one measured
10.014-second cold/warm request); inputs/responses and token budgets
remain capped. This does not promise a 30-second total execution deadline
or an SLA, and timeout still rejects without leaking response/source text. Response model and JSON must match the strict contract.
Raw server errors, exceptions, documents and response bytes never appear
in error messages. After a 30s bound alone did not yield stable review
coverage (5/9 invented fixture attempts admitted), a subsequent trivial
prompt probe suggested repeated model loading was expensive. The adapter
now requests fixed `keep_alive="1m"` **only for the synthetic-only local
model**, rather than unloading it immediately after every request.
Ollama may keep approximately 1.7 GB model memory resident for up to
one minute after a request (actual memory behavior is host-dependent).
This change does **not** raise the 30s socket timeout, alter request/response
or token budgets, claim semantic standards or acceptance criteria, or prove
reliable performance on lengthy H&M fixtures. Runtime reuse and latency
must be independently observed again on the operator PC.

### Activation contract

- Default remains `AI_PROVIDER=disabled` and
  `AI_LOCAL_EXPERIMENTAL_ENABLED=false`. All existing deployments keep
  their prior behavior.
- Registry returns the experimental provider only when
  `APP_ENV=development` or `test`,
  `AI_PROVIDER=ollama_local`,
  `AI_LOCAL_EXPERIMENTAL_ENABLED=true` and
  `AI_MODEL=qwen3:1.7b`. No arbitrary model, endpoint or remote host.
- **Pilot/staging/production deny the experiment**, both in provider
  registry and in deployment preflight, even if someone sets the flag.
- Only an explicit `AIRequest.metadata` exactly equal to
  `{"synthetic_local_ai_test": true}` (strict boolean) may reach the
  transport. Normal Claim/Document jobs carry claim/document lineage
  metadata and therefore fail before opening a socket. This marker is
  **not proof of consent or synthetic provenance**: an eventual
  authorized caller must independently ensure only invented samples
  can be marked as synthetic.
- There is no HTTP API route or worker consumer for submitting these
  requests; no production document path has been authorized to use them.
- Source quote verification and human review remain separate from
  this transport adapter. The #756 synthetic quote gate is *not yet
  called* by the provider and does not prove semantic claims.

### CI scope

`apps/api/tests/test_ollama_local_experimental.py` uses a fake
`HTTPConnection`. It checks exact destination/body, including fixed 1m retention on
sequential synthetic requests, successful
structured output, old disabled default, environment and marker gates,
wrong model, oversize, non-200 response, invalid JSON/shape, wrong model
reply, socket errors, response limits and privacy-safe failure codes.

`scripts/tests/test_pilot_local_ollama_adapter_policy.py` is also
included in the stable **Production environment policy** CI step.

**CI tests do not start a real Ollama daemon.** The operator ran an earlier
standalone localhost timing probe, but has not yet run a post-change H&M
repeatability check. CI cannot prove
GPU execution, source-semantic quality, independently verified model
digest, throughput/latency, an approved isolated pilot host, actual
network egress restrictions of the entire stack, or readiness for
real insurer data. The current local model string is a *temporary
allowlisted tag*, **not** an immutable verified model digest. Pin and
attest a trusted model artifact/version before future model processing
authority.

### Next bounded slices

1. Build a single **synthetic-only authorized caller** connected to
   the source-custody review queue, preserving version/prompt/tenant
   metadata and human review; never promote generated opinions to
   authoritative claim facts.
2. Evaluate invented complete/missing/conflicting H&M machinery records
   with independent expected answers, actual citations, refusal criteria
   and measured resource use/latency on an isolated Ollama runner.
3. Independently validate the actual selected model digest and
   deployment network rules; rework any shared-container topology,
   resource isolation and operator recovery for an approved pilot.
4. Keep `AI_PROVIDER=disabled` and external APIs off in the actual
   customer candidate until the R5 and relevant operational gates pass.

**No real customer files or personal identifiers should enter this
experimental provider. Pilot GO remains NO.**
