# Issue #752: synthetic-only Windows H&M post-retention observation (2026-10-24)

**Status:** operator-reported actual local console outputs, **not independently attested**.
On `main@7fc8bdfef3db51152a6e309acbc4e3b422624a9a` (merged PR #798),
the experiment used development-only Ollama `qwen3:1.7b`, fixed literal
`127.0.0.1:11434`, `keep_alive="1m"`, and a 30s socket read timeout.
No real claim, uploaded document, customer identifier, external inference
API, production AI activation, or release authorization was used.

The initial invocation failed **before contacting Ollama** with
`ModuleNotFoundError: No module named 'app'` because the isolated Windows
Python process had not been given `apps/api` on `PYTHONPATH`. The
operator later supplied the successful fixed synthetic CLI outputs.
This import setup error is **not** a failed H&M inference observation.
A pre-test `ollama ps` snapshot showed a locally resident `qwen3:1.7b`
tag, 100% GPU, context 4096; it does not prove the weights or all
subsequent executions were independently verified.

## Three invented machinery-loss scenarios

The command was `scripts.pilot_local_ai_hm_loopback_smoke` with its
exact explicit opt-in flag. The output said `all_accepted_for_human_review=true`.

| Invented fixture | Observed elapsed | Source quote gate | Critical literal coverage | Deterministic baseline exact matches / missing | Other source-backed quotes |
| --- | ---: | --- | ---: | ---: | ---: |
| `complete_records` | 11,243 ms | Accepted for human review | 4 / 4 | 0 / 3 | 3 |
| `missing_engine_records` | 5,325 ms | Accepted for human review | 4 / 4 | 0 / 3 | 3 |
| `conflicting_alarm_times` | 5,581 ms | Accepted for human review | 3 / 3 | 0 / 3 | 3 |

The three recorded elapsed times total **22,149 ms**. This is the sum
of local per-case measurements, not a general end-to-end latency SLA.
**All nine deterministic baseline exact-quote references were missing,
even though source-backed alternative quotes and critical phrase
requirements were observed.** A source-substring gate cannot independently
establish causal accuracy, evidence completeness, reliability of
attribution, or safe claims settlement recommendations.

## Nine-call fixed repeat and local tag drift observation

The command was `scripts.pilot_local_ai_hm_digest_guard_smoke` with its
exact opt-in flag, which executes three rounds of the same three invented
fixtures (9 calls total). Operator stdout reported:

| Fixture | Source-quote accepted | Incomplete | Rejected |
| --- | ---: | ---: | ---: |
| `complete_records` | 3 | 0 | 0 |
| `missing_engine_records` | 3 | 0 | 0 |
| `conflicting_alarm_times` | 3 | 0 | 0 |
| **Total** | **9** | **0** | **0** |

`local_tag_digest_same_before_after=true` reports only agreement of
two **untrusted read-only registry snapshots**; it does not attest
the weights or the model executed on every inference. The script
also explicitly returns `repeatability_proven=false`,
`model_digest_attested=false`, `model_artifact_independently_attested=false`,
`network_egress_isolation_verified=false`,
`expert_ground_truth_approved=false`, `human_review_completed=false`,
and `pilot_accepted=false`.

## Interpretation against pre-#798 operator evidence

Previously with `keep_alive=0`, the post-30s-timeout synthetic three-case
trial reported 18,045ms (accepted), 29,936ms (accepted), and 30,017ms
(runtime unavailable/rejected). The nine-case repeat admitted **5/9**
and rejected **4/9** source-quote checks. The new **3/3** and **9/9**
observations are encouraging but measured under uncontrolled local host
conditions, warm/cold state, and no matched native long-prompt timing
study. A causal speed claim, model quality claim, and reliability
guarantee are **not** justified by this small comparison.

## Next gates: do not promote to customer pilot

1. Prepare blinded independent expert H&M source assessment **before**
   reviewing model candidates: source/version accuracy, meaningful
   omissions, contradictions, unsupported inferences, and no-model
   reference comparison. Use the [non-approving expert checklist](LOCAL_AI_HM_INDEPENDENT_EXPERT_REVIEW.md);
   keep real reviewer records and model prose out of GitHub.
2. Review why all three scenarios used alternate source-backed quotes
   while exact deterministic baseline matches were zero. This is a
   **review priority**, not automatic proof of hallucination or failure.
3. Separately pin/attest actual local model artifact and execution
   provenance; verify entire-host egress controls, data authorization,
   human oversight and operational acceptance in an approved environment.

**Pilot GO=NO.** This report documents the supplied bounded diagnostic
counts only; issue #752 remains open. GitHub issue evidence:
https://github.com/eh3aneba/maritime-claims-platform/issues/752
