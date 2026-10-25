# #752 — Post-blind local AI source-quote preview (invented evidence only)

Existing 3/3 and 9/9 synthetic count-only results do not show which
excerpts Qwen selected. An independent H&M specialist cannot adjudicate
selective quotation, omitted uncertainty or factual conflation without
access to the model-selected snippets **after** an independent reference
has been frozen. This tool offers an optional Phase 2 preview of only
**verified literal substrings** from the nine fixed **invented** source
records, with source ID, version, kind and character offsets. It
reconstructs each displayed excerpt from the code-owned source body
after strict source/version/substring validation. A rejected model
candidate outputs only a fixed error category, never unsafe model prose.

## Strict separation of review phases

1. First give the independent H&M expert **only** the
   [neutral Phase 1 source packet](LOCAL_AI_HM_NEUTRAL_BLIND_PHASE_ONE.md)
   with CASE-01 through CASE-03 and identical general questions.
   Have them record source/version attributions, uncertainties and
   independently supported findings privately. Freeze the reference
   with reviewer governance, timestamp, source-packet hash and
   version in an approved access-controlled system, outside GitHub.
2. **Only after** independent reference coding is frozen should an
   authorized operator on the Windows development PC run the Phase 2
   manual command below. The command **cannot independently attest**
   that the reference was frozen or an H&M specialist was actually
   blinded: the opt-in flag enforces only explicit operator intent.
3. Compare the safe selected excerpts against the independent expert's
   prior coding using the [post-blind keyed checklist](LOCAL_AI_HM_INDEPENDENT_EXPERT_REVIEW.md).
   Investigate unsupported causal inferences, missing records confused
   with nonexistent records, unverified reports mistaken for facts,
   conflicting accounts silently reconciled and incomplete quotations.
   Record disagreements and expert decisions privately. A code-owned
   text-substring success is **not** expert validation.

## Manual command on the local Windows PC

Run from the SeeClaims repository root; Ollama with qwen3:1.7b must be
running. The existing experimental adapter connects only to literal
`127.0.0.1:11434`.

```powershell
$env:PYTHONPATH = "$(Get-Location)\apps\api;$(Get-Location)"
& .\.venv-local-ai\Scripts\python.exe -m scripts.pilot_local_ai_hm_postblind_model_quotes --reveal-fixed-synthetic-ollama-quotes-for-postblind-review
```

Without that **exact** flag, no provider is constructed and nothing is
sent even to localhost. The command runs exactly three invented,
code-owned source-quote requests. A *source-backed but incomplete*
candidate can still be inspected, but is marked
`source_quotes_incomplete_for_review`. Unsupported, malformed, wrong
source-version, wrong model-tag or invented text is rejected **without
any invalid quote being printed**. The CLI never emits non-source
free-form model interpretation.

It accepts no customer/tenant files, arbitrary input, Evidence loader,
private claim details, external inference API or reviewer response;
it writes no report files, databases, claim facts, reserves or payments.
The output intentionally includes **invented synthetic quotations** on
the local console. Do not show Phase 2 output during the initial blind
review, and do not route real insurer Evidence through this tool.
The separate count-only diagnostics remain preferable for routine
operator checks.

This tool does not independently verify actual execution identity or
model weights. Its Phase 1 packet digest is an *unattested drift
observation*, not a signature. All blindness, reference-freeze, expert
label, expert review, model attestation, egress security and pilot
approval flags are set to FALSE.

Focused no-network regressions:

```bash
pytest -q apps/api/tests/test_local_ai_hm_postblind_model_quotes.py
python -m unittest scripts.tests.test_pilot_local_ai_hm_postblind_quote_policy -v
```

**Pilot GO=NO.** No real/customer claims, H&M causation decision,
coverage determination, reserve, settlement or production release.
