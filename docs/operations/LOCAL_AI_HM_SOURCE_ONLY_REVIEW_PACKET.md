# #752 — source-only packet for blind independent H&M reference review

**For the first *unprimed* assessment, prefer the [neutral Phase 1
packet](LOCAL_AI_HM_NEUTRAL_BLIND_PHASE_ONE.md)**. This older packet
exposes scenario-specific criteria; reserve it for the separately
controlled *post-reference* phase, after independent labels are frozen.
Neither file proves an expert was actually blinded.

The existing checklist in #772 describes **what** an independent H&M
machinery claims specialist should judge. This companion tool supplies
**only the nine invented, versioned source records** across the three
synthetic turbocharger-loss cases, alongside unanswered review criteria.
It deliberately includes **no model-generated content**, no code-authored
reference candidate, no acceptance counts and no prefilled expert answers.

From the root of the checked-out SeeClaims repository, run manually:

```powershell
python -m scripts.pilot_local_ai_hm_source_only_review_packet --print-invented-hm-source-only-packet
```

The script prints a bounded JSON packet to standard output. This output
**does contain the invented source texts** so a specialist can actually
review them. Use only those synthetic sources. Do not replace them with
real insurer or customer documents, and do not publish a real claim in
GitHub issues, Actions logs or attachments.

The output is computed from the code-owned fixture catalog. It contains
a deterministic SHA-256 of the exact packet's cases to help detect local
reference drift across copies. That hash is **not independent source
attestation**, does not attest operator identity, and cannot prove that
an independent reviewer was actually blind. Only a separately managed
blind reference-coding process can do that.

## Review protocol

1. Give an independent H&M specialist this source-only packet **before**
   any model output, score, literal baseline or model error report. Check
   conflicts of interest and document assessor identity separately in
   an approved access-controlled human-review system.
2. Ask them to record *per source ID and version*: what is explicitly
   reported, what is missing or unknown, what conflicts and which
   conclusions would require further evidence. Distinguish an alleged
   engine failure from verified mechanical causation.
3. Do not equate **not supplied** engine logs with records that never
   existed. Preserve the engineer's and workshop's conflicting alarm
   times as independent unresolved accounts.
4. Record independently coded judgments, reviewer disagreements and
   adjudication privately, **not** in this CLI, repository or GitHub CI.
5. Only after reference coding is finalized may a project reviewer
   compare that independent reference with separately obtained
   synthetic model outputs. A source substring match alone is not
   professional H&M claims assessment.

No user file path, manual source text, login, reviewer details or
approval flag is accepted as CLI input. No network request, AI inference,
file write or case mutation is performed. Every item is sourced only
from the three fixed invented fixtures, with a `Synthetic ` prefix.
The script returns an error if those source shapes drift unexpectedly.

The fields `expert_reference_approved`,
`independent_expert_labels_collected`, `reviewer_blindness_verified`,
`pilot_accepted` and `source_packet_digest_independently_attested`
are always false. A successful command means only that the **blank,
source-only planning packet** could be printed.

Offline tests:

```bash
python -m unittest scripts.tests.test_pilot_local_ai_hm_source_only_review_packet -v
```

**Pilot GO=NO.** No real blinded expert coding, locally measured real
Ollama performance, independently verified model digest, host egress
security controls or insurer authorization has been established here.
