# P0 #461 — Disposable exact-head preactivation proof PR

**Status:** operator-only synthetic GitHub branch-protection rehearsal, never a
customer-data pilot or a production ruleset update.

This file deliberately creates a **small, non-draft, same-repository PR
against current `main`** with no runtime/code/config changes. It exists to
produce a freshly observed **open PR HEAD** on which GitHub Actions can emit
the eleven exact required-check contexts before the repository Admin activates
the seven currently missing contexts. A *merged historical PR* does not satisfy
the open-PR guard in `scripts/pilot_required_check_preflight.py`.

## Stage A: green preactivation

1. Leave this disposable PR **open**, with no merge conflicts and all six
   independent workflows complete. Do not assume a workflow-level green
   result means all eleven stable check names exist.
2. For the exact, current 40-character PR head SHA, use a private run of
   `scripts/pilot_required_check_preflight.py` with `--repo
   eh3aneba/maritime-claims-platform`, this PR number and `--sha`.
   It paginates all GitHub check runs, rejects duplicate/wrong-source names
   and needs **11/11 distinct `completed/success` stable contexts**.
3. An authorized GitHub Admin may inspect the existing active `Protect main`
   ruleset ID **20842512** and the **dry-run-only**
   `scripts/pilot_ruleset_admin_activation.py` instructions in
   `docs/operations/BRANCH_PROTECTION_REQUIRED_CHECKS.md`.
   Current settings are *not* modified by opening this PR. For write actions
   the Admin must have a change ticket, the required permissions and an
   exclusive operator-controlled change window.
4. Preserve independent proof that the active ruleset actually changed from
   **4/11 to 11/11**; do not infer this from the existence of the admin tool.

## Stage B: failing-check enforcement exercise — only after 11/11

This is **not** a deliberately failing PR yet. Only after a successful
Admin ruleset activation and independent 11/11 readback, a separate
operator-controlled synthetic test commit may exercise one of the **newly**
required, fixed-name jobs — with no customer data, no bypass, and all other
required checks green. The operator must verify that the red required check
actually causes GitHub to refuse merge, not merely that the PR happens to be
unmergeable for some other reason.

After the red observation, repair the same disposable PR on a different SHA,
prove all eleven required checks green, and confirm the merge restriction
cleared. The read-only
`scripts/pilot_ruleset_negative_enforcement.py` captures matching
red/blocked and green/clean metadata, but intentionally never pretends to
have executed a GitHub merge refusal, and **does not authorize Pilot GO**.

**Safety:** Never merge the red phase, lower safeguards for testing, create
bypass actors, or expose private Admin tokens, customer files, or credential
references in GitHub issue comments. If this PR is no longer open, its HEAD
changes or a rule changes, restart the preactivation proof with a fresh,
reviewed open-PR SHA.

**Closeout:** `#461` stays OPEN until the Admin changes active settings,
independently verifies live 11/11 and completes the red/refused/green recovery
experiment. The broader real-data Pilot remains **NO-GO**.
