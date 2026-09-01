import { API_BASE, ApiError } from "./api";

export type RecoveryTimebarStatus = "triggered" | "not_triggered" | "insufficient_evidence" | "not_applicable";
export type RecoveryTimebarUrgency = "low" | "medium" | "high" | "critical";
export type RecoveryTimebarDecisionAction = "accept" | "edit" | "dismiss" | "not_applicable";

export interface RecoveryTimebarDecision {
  id: string;
  evaluation_id: string;
  decided_by_id: string | null;
  converted_task_id: string | null;
  evaluation_hash: string;
  decision_number: number;
  action: RecoveryTimebarDecisionAction;
  note: string;
  edited_candidate_implication: string | null;
  edited_recommended_action: string | null;
  edited_due_date: string | null;
  previous_decision_hash: string | null;
  decision_hash: string;
  decided_at: string;
}

export interface RecoveryTimebarEvaluation {
  id: string;
  snapshot_id: string;
  evaluation_key: string;
  kind: "recovery" | "timebar";
  status: RecoveryTimebarStatus;
  title: string;
  counterparty: string | null;
  candidate_basis: string | null;
  trigger_date: string | null;
  period_value: number | null;
  period_unit: string | null;
  candidate_deadline: string | null;
  days_remaining: number | null;
  urgency: RecoveryTimebarUrgency;
  rationale: string;
  candidate_implication: string;
  recommended_action: string;
  missing_prerequisites: string[];
  source_refs: Array<Record<string, unknown>>;
  evaluation_hash: string;
  latest_decision: RecoveryTimebarDecision | null;
}

export interface RecoveryTimebarSnapshot {
  id: string;
  claim_id: string;
  generated_by_id: string | null;
  snapshot_version: number;
  engine_version: string;
  source_state_hash: string;
  snapshot_hash: string;
  summary: Record<string, unknown>;
  generated_at: string;
  evaluations: RecoveryTimebarEvaluation[];
}

export interface RecoveryTimebarDashboard {
  claim_id: string;
  snapshot: RecoveryTimebarSnapshot | null;
  disclaimer: string;
}

export interface RecoveryTimebarDecisionInput {
  action: RecoveryTimebarDecisionAction;
  evaluation_hash: string;
  note: string;
  edited_candidate_implication?: string | null;
  edited_recommended_action?: string | null;
  edited_due_date?: string | null;
  convert_to_task?: boolean;
}

async function parse<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    let detail = `${fallback} (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // Safe fallback for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function getRecoveryTimebar(claimId: string): Promise<RecoveryTimebarDashboard> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar`, { credentials: "include" });
  return parse<RecoveryTimebarDashboard>(response, "Recovery & time-bar intelligence could not be loaded");
}

export async function buildRecoveryTimebar(claimId: string): Promise<RecoveryTimebarSnapshot> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/build`, {
    method: "POST",
    credentials: "include",
  });
  return parse<RecoveryTimebarSnapshot>(response, "Recovery & time-bar intelligence could not be refreshed");
}

export async function decideRecoveryTimebar(
  claimId: string,
  evaluationId: string,
  payload: RecoveryTimebarDecisionInput,
): Promise<RecoveryTimebarDecision> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/evaluations/${evaluationId}/decision`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<RecoveryTimebarDecision>(response, "Recovery & time-bar decision could not be recorded");
}
