# Pilot v1 release candidate v4 — historical security admission

**HISTORICAL v4 DOCUMENT — no longer the active release-record format.** Current release candidates use [v5 signed-PDF admission](PILOT_RC_V5_SIGNED_PDF_ADMISSION.md) and `mcri-pilot-rc-v5`; never submit an old v4 record for Pilot GO. This guide preserves the independently required historical-secret disposition controls from v4. The gate is structural, NOT approval to process real customer claims.
Related: [#764](https://github.com/eh3aneba/maritime-claims-platform/issues/764), [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653), [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647), and [Security workflow](../../.github/workflows/supply-chain.yml).

## Why v4

The v3 record required `supply_chain_exact_head=pass` for a release candidate. But the PR / exact-head **Secret history scan** can be green while the **weekly scheduled full-history Gitleaks scan** continues reporting eight August 2026 historical findings (see #764). A green source check is not evidence that every historic credential-like finding was independently classified. A structurally complete v3 record could omit this separation.

The historical v4 validator introduced **`mcri-pilot-rc-v4`** and the unconditional `historical_secret_findings_disposition` proof. The **current v5 validator rejects all v1/v2/v3/v4 records**; do not relabel existing JSON or copy historic `pass` values. Reconstruct a new private release record from current evidence. All three runtime feature choices and the no-go boundaries from the [historical v3 feature guide](PILOT_RC_V3_FEATURE_ADMISSION.md) still apply.

## Required independent security evidence

An accountable independent security owner must establish and privately retain all of the following **before** setting `proofs.historical_secret_findings_disposition.result` to `pass`:

1. **Scope:** the exact eight historical matches identified in #764, including their old commit/path/line and a separate confidential case ID for each. These repository locations alone do not establish that any matched value is a live key.
2. **Classification:** each matching value is privately compared to authorized credential inventories and deployment/service access records. Record individually `synthetic_confirmed`, `real_revoked_and_audited`, or `unresolved` with the reviewer and dated evidentiary reference. A superficial test-file path is not sufficient evidence for `synthetic_confirmed`.
3. **Remediation:** any actual credential is revoked/rotated, access checked and incident process completed, with a separate restricted incident reference. Do not commit raw values, service identities, logs, private access data, or Gitleaks matched bytes to source control.
4. **Exceptions:** for independently established synthetic fixtures only, separately review the narrow fingerprint scope. Never disable `generic-api-key`, alter the mandatory workflow, downgrade scanner enforcement, or blindly apply a blanket baseline. Existing `.gitleaksignore` contents must be reviewed as-is before proposing further changes.
5. **Verification:** rerun a **scheduled-equivalent full-history** Gitleaks scan on the exact reviewed repository history; document GitHub run/attempt, commit SHA, scan range, complete `Secret history scan` result, and any unresolved finding. An unrelated pull-request `success` does not count. A failed or incomplete full-history run does not count. Verify protected PR scans continue detecting new secrets.
6. **Independent decision:** record the named security owner/reviewer, decision timestamp (canonical UTC), private evidence package reference and scope/expiry of any exceptions. Release owner separately verifies this evidence before submitting an RC for acceptance. A scanner result alone is not an independent security sign-off.

**Current baseline (15 November 2026):** the last observed *scheduled* Supply Chain run was [#42606676643](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42606676643) from November 9. Its Secret History job reported eight matches and failed. Newer pull-request and main-push workflows have been green but do not retroactively resolve the weekly audit. The new proof must therefore remain `pending` until independently verified; do not manufacture a new date, approval or scan result.

## Private RC record workflow

For a **new** release candidate, use v5 in access-controlled local storage, never a v4 draft or this repository:

```sh
python -m scripts.pilot_rc_gate init \
  --release-sha "<independently-verified-exact-40-character-sha>" \
  --output /secure/pilot-releases/rc-v5.json
```

The new proof starts as:

```json
{
  "result": "pending",
  "evidence_ref": "",
  "owner": "",
  "observed_at_utc": ""
}
```

These historical-secret requirements remain mandatory in v5; a separate **signed-PDF inbound scope/security disposition** is also unconditionally required. Follow the [v5 admission guide](PILOT_RC_V5_SIGNED_PDF_ADMISSION.md) before submitting a record. Only after completing all six requirements above, the authorized operator may populate the historical-secret proof with `pass`, a **non-secret reference** to the private signed security decision, accountable owner, and actually observed UTC timestamp. Then validate **only record shape and completeness**:

```sh
python -m scripts.pilot_rc_gate check \
  /secure/pilot-releases/rc-v5.json \
  --expected-sha "<independently-verified-exact-40-character-sha>"
```

The validator does **not** query GitHub, inspect true Gitleaks findings, verify the reviewer, confirm rotations, assess certificate trust or authorize deployment. It rejects missing, pending, `not_applicable`, invalid timestamps and missing owners, but cannot prove that an entered `pass` is truthful. A separate accountable release decision and all other #653/#647 Pilot P0 gates remain mandatory. **Real-data Pilot GO=NO until independently approved.**
