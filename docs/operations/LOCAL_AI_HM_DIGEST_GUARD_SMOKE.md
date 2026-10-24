# #752 — observe local model digest drift across nine invented H&M cases

This opt-in development-only runner adds **two read-only Ollama model-tag
snapshots**, before and after the existing **nine** fixed synthetic
H&M test requests (3 scenarios × 3 sequential rounds). Each snapshot
reads the code-fixed tag `qwen3:1.7b` from the local `/api/tags`
endpoint on **127.0.0.1:11434**, then checks whether the two reported
64-character SHA-256 digests are identical.

## PowerShell on the PC with Ollama

From the SeeClaims repository root, with Ollama running and
`qwen3:1.7b` installed:

```powershell
ollama list
$env:PYTHONPATH = "$(Get-Location)\apps\api;$(Get-Location)"
& .\.venv-local-ai\Scripts\python.exe -m scripts.pilot_local_ai_hm_digest_guard_smoke --run-fixed-synthetic-ollama-digest-guard
```

The CLI refuses to contact even localhost without this exact flag.
There is no customer document loader, arbitrary input text or path,
production AI switch, remote inference service or network destination
other than the existing loopback Ollama adapter.

A valid preflight snapshot must report the expected tag, one correctly
formed SHA-256 digest, and explicitly FALSE provenance/authorization
flags. Missing, malformed, contradictory or already-attested
observations **fail closed before any model request**. If the preflight
passes, exactly nine invented synthetic source-quote requests execute.
The postflight snapshot must again be valid. Any changed digest makes
`guarded_observation_accepted_for_human_review=false` and yields a
nonzero CLI exit even when all nine quoted outputs were accepted.

## What the summary does and does not establish

Only bounded counts per scenario, the fixed tag, the two-snapshot
comparison boolean and fixed FALSE attestation/approval flags are
printed. Each scenario now carries separate counts of rounds whose three
fixed fact/qualifier pairs were complete or incomplete in the **same
source-backed excerpt**, plus rounds not evaluated after rejection and
the bounded missing-pair total. These are NON-GATING context diagnostics;
even with missing pairs, an otherwise valid quote/digest result retains
its previous exit status. None is a professional interpretation. The
`context_preservation_expert_verified=false` flag is fixed. **Neither digest value, source content, model response nor
network error details are printed**. The CLI does not save an artifact.

Matching digest observations are **not independent attestation** of
model weights, actual execution identity, machine integrity, network
isolation, inference reproducibility or H&M expert agreement. The local
tag registry could be untrusted, the model could switch between the
two snapshots, or the snapshots could return the same digest despite
other runtime changes. The exact-source quote gate and synthetic
critical coverage are development checks, not professional claims
assessment or fact verification.

`pilot_accepted=false`, `model_digest_attested=false`,
`model_artifact_independently_attested=false`, and
`expert_ground_truth_approved=false` remain unchanged even if every
synthetic request passes and the two snapshots match. A matching
observation must never be used as authorization for insurer customer
Evidence.

No CI run contacts an actual Ollama model; mock-only backend and
source-policy regressions exercise all failure scenarios:

```bash
pytest -q apps/api/tests/test_local_ai_hm_digest_guard_smoke.py
python -m unittest scripts.tests.test_pilot_local_ai_hm_digest_guard_policy -v
```

**Pilot GO=NO.** Before a genuine claims pilot, the operator must run
and review the local experiments, an independent expert must label
H&M source evidence, and security must attest the runtime model,
network isolation and customer-data controls.
