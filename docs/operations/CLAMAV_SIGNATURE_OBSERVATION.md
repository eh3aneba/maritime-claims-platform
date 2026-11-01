# Synthetic read-only signature version/age observation (#653)

This tool records daemon-reported metadata. It does not update definitions,
submit documents, read claim storage/DB, scan files, change scanner settings,
set readiness, or change customer-evidence admission. It defines **no acceptable
freshness threshold**. Security-owner policy and independent host acceptance
remain necessary; observation success is not scanner/Pilot approval.

From the repository root, with an explicitly isolated synthetic clamd on
loopback port 13310 (or 3310):

```bash
APP_ENV=test MCRI_SYNTHETIC_ONLY_CONFIRM=YES \
python scripts/pilot_clamav_signature_observation.py \
  --release-sha "$(git rev-parse HEAD)" \
  --port 13310 --signature-timezone UTC \
  --output artifacts/clamav-signature-observation.json
```

The output file must not exist. Only the bounded `zVERSION` protocol command is
sent; destination is fixed IPv4 loopback. No customer byte stream, updater/log
payload, credentials or raw daemon response is retained. Missing, malformed,
oversized, unterminated or unreachable metadata produces an unknown-state record
and a nonzero exit; output creation failures also fail. No existing evidence file
is overwritten. The optional CI workflow tests the pure observer with mocked
transport and fixed clocks; it does not query a live production scanner and adds
no required context or exception to the existing eleven checks.

## Timestamp interpretation and limits

VERSION's English date has no UTC offset. The operator must explicitly declare
UTC only after checking the synthetic daemon's timestamp context. Omitting that
declaration records the version but leaves age unresolved and exits nonzero.
The observer never silently applies the observer host's timezone. The declaration
is recorded as an assertion, not independent timezone verification.

An aware observation clock is converted to UTC. The report records a signed
integer age in seconds, not a pass/fail age range. Future timestamps are explicit
and return nonzero, rather than being clamped to a fresh zero. Even arbitrarily
old, syntactically valid metadata can be **observed** successfully; that never
means it is acceptable for evidence admission. No raw transcript, source text,
hostname or filesystem path from daemon output is copied into the artifact.

`operator_supplied_release_sha` is a supplied candidate reference, not proof that
the scanner belongs to that deployed release. Record the observer's actual Git
SHA/tree and scanner image digest with the operator's execution evidence. The
tool explicitly leaves release binding, signature authenticity, current malware
coverage, production scanner attestation and Pilot approval false.

## Regression and operational evidence

```bash
python -m unittest scripts.tests.test_pilot_clamav_signature_observation \
  scripts.tests.test_pilot_live_clamav_probe -v
```

Fixed-clock tests cover exact/zero/arbitrarily old ages, future dates, aware
offset clocks, absent timezone, malformed/missing dates, invalid weekday/serial,
bounded fragmented framing, the exact VERSION-only request, synthetic guard,
redacted failures, and exclusive output creation. They do not invent a maximum
age or classify definitions as fresh/stale.

Next operator evidence: trusted clock/timezone context, daemon/image identity,
signed-definition verification, updater result/reachability and observed engine/
definition metadata from the selected isolated host. A security owner must then
approve a maximum-age/unknown-clock/update-failure policy before a separate
admission/readiness change is designed. Preserve signed-CVD checks, TLS trust,
network policy, clean/EICAR tests and operator alert receipt; never obtain a green
result by disabling verification or inferring freshness from PING alone.
