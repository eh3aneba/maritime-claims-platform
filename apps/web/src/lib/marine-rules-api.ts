import { API_BASE, ApiError } from "./api";

export type MarineRuleDecisionAction = "accept" | "edit" | "dismiss" | "not_applicable";

export interface MarineRuleDecision {
  id: string;
  rule_run_id: string;
  decided_by_id: string | null;
  rule_id: string;
  rule_version: string;
  evaluation_hash: string;
  decision_number: number;
  action: MarineRuleDecisionAction;
  note: string;
  edited_candidate_implication: string | null;
  edited_recommended_action: string | null;
  previous_decision_hash: string | null;
  decision_hash: string;
  decided_at: string;
}

export interface MarineRuleDecisionInput {
  evaluation_hash: string;
  action: MarineRuleDecisionAction;
  note: string;
  edited_candidate_implication?: string | null;
  edited_recommended_action?: string | null;
}

export async function decideMarineRuleEvaluation(
  claimId: string,
  runId: string,
  ruleId: string,
  payload: MarineRuleDecisionInput,
): Promise<MarineRuleDecision> {
  const response = await fetch(
    `${API_BASE}/claims/${claimId}/rules/runs/${runId}/evaluations/${encodeURIComponent(ruleId)}/decision`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    let detail = `Marine rule decision failed (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // Preserve the safe fallback for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<MarineRuleDecision>;
}
