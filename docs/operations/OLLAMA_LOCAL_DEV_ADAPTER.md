# Experimental local Ollama adapter — Issue #752

**Status:** implemented **development-only**, mock-transport CI tested,
**not deployed, not tested against a real Ollama daemon, not pilot-authorized**.
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
inference provider. Timeout is 10 seconds; inputs/responses and token
budgets are capped. Response model and JSON must match the strict contract.
Raw server errors, exceptions, documents and response bytes never appear
in error messages.

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
`HTTPConnection`. It checks exact destination/body, successful
structured output, old disabled default, environment and marker gates,
wrong model, oversize, non-200 response, invalid JSON/shape, wrong model
reply, socket errors, response limits and privacy-safe failure codes.

`scripts/tests/test_pilot_local_ollama_adapter_policy.py` is also
included in the stable **Production environment policy** CI step.

**None of these tests starts a real Ollama daemon.** They cannot prove
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
