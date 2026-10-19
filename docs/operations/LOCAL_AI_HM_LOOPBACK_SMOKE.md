# #752 — explicit local-only Ollama smoke for the three invented H&M cases

This **follow-on experimental development step**, built on the synthetic
case matrix in PR #762, can invoke the existing fixed IPv4 loopback adapter
at `127.0.0.1:11434` using **only code-owned invented scenarios**. It does
not load arbitrary files, requests, uploaded Evidence or tenant/customer data.
Neither this script nor its tests activate `AI_PROVIDER` in the application.

Run from the repository root **on a PC running Ollama**, after confirming
`qwen3:1.7b` is installed and the local server is reachable. On Windows
PowerShell:

```powershell
ollama list
$env:PYTHONPATH = "apps/api"
python -m scripts.pilot_local_ai_hm_loopback_smoke --run-fixed-synthetic-ollama
```

With no flag or with any other argument, the command refuses to connect.
The smoke uses the already-existing experimental adapter with literal
`127.0.0.1`, no DNS/proxy/external inference API, JSON schema output,
low output budget, timeout, and three **sequential** fixed requests.
Tests use injected mock providers and **do not execute a real Ollama model**.

**Output restriction:** prints only scenario names, exact source-quote
attribution and literal no-model baseline match counts, measured
per-call elapsed milliseconds, acceptance/rejection, and explicit
`model_digest_attested=false`, `expert_ground_truth_approved=false`,
`local_transport_attested=false`, `pilot_accepted=false`. It does
not print model prose, prompts, source bodies or customer identifiers,
and does not write receipts or claim decisions to storage. The presence
of `all_accepted_for_human_review=true` is merely a **source-substring
syntax result**, not a quality, truth, model-identity, human-approval or
production-readiness result. Selectively quoted or conflicting facts may
remain misleading. No external model API or third-party egress is used
by this code; independent host/network controls and server logs still
require review.

Any unsupported/hallucinated quote is rejected without exposing prose;
the runner continues to the next invented scenario and returns a
nonzero exit if any scenario was rejected. Actual model performance,
token cost, model artifact digest, reproducibility and an independent
H&M expert reference **are not established by CI**.

Unit tests:

```bash
pytest -q apps/api/tests/test_local_ai_hm_loopback_smoke.py
python -m unittest scripts.tests.test_pilot_local_ai_hm_loopback_policy -v
```

**Pilot GO=NO**. No real insurer Evidence or user content is authorized.
Before a genuine pilot: independent expert baseline, runtime model digest
attestation, network isolation, reproducible measured acceptance, tenant
and Evidence authorization, human reviewer accountability, and operational
sign-off must be separately established.
