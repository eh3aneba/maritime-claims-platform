import { API_BASE, ApiError } from "./api";

export type SeverityReserveStatus = "triggered" | "not_triggered" | "insufficient_evidence" | "not_applicable";
export type SeverityReserveDecisionAction = "accept" | "edit" | "dismiss" | "not_applicable";

export interface SeverityReserveDecision {
  id: string;
  evaluation_id: string;
  decided_by_id: string | null;
  evaluation_hash: string;
  decision_number: number;
  action: SeverityReserveDecisionAction;
  note: string;
  edited_severity_label: "low" | "medium" | "high" | "critical" | null;
  edited_lower_amount: string | number | null;
  edited_upper_amount: string | number | null;
  previous_decision_hash: string | null;
  decision_hash: string;
  decided_at: string;
}

export interface SeverityReserveEvaluation {
  id: string;
  snapshot_id: string;
  evaluation_key: string;
  kind: "severity" | "reserve";
  status: SeverityReserveStatus;
  title: string;
  severity_label: "low" | "medium" | "high" | "critical" | null;
  severity_score: number | null;
  currency: string | null;
  lower_amount: string | number | null;
  upper_amount: string | number | null;
  rationale: string;
  candidate_implication: string;
  recommended_action: string;
  factors: Array<Record<string, unknown>>;
  missing_prerequisites: string[];
  source_refs: Array<Record<string, unknown>>;
  evaluation_hash: string;
  latest_decision: SeverityReserveDecision | null;
}

export interface SeverityReserveSnapshot {
  id: string;
  claim_id: string;
  generated_by_id: string | null;
  snapshot_version: number;
  engine_version: string;
  source_state_hash: string;
  snapshot_hash: string;
  summary: Record<string, unknown>;
  generated_at: string;
  evaluations: SeverityReserveEvaluation[];
}

export interface SeverityReserveDashboard {
  claim_id: string;
  snapshot: SeverityReserveSnapshot | null;
  disclaimer: string;
}

export interface SeverityReserveDecisionInput {
  action: SeverityReserveDecisionAction;
  evaluation_hash: string;
  note: string;
  edited_severity_label?: "low" | "medium" | "high" | "critical" | null;
  edited_lower_amount?: string | null;
  edited_upper_amount?: string | null;
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

export async function getSeverityReserve(claimId: string): Promise<SeverityReserveDashboard> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/severity-reserve`, { credentials: "include" });
  return parse<SeverityReserveDashboard>(response, "Severity & reserve support could not be loaded");
}

export async function buildSeverityReserve(claimId: string): Promise<SeverityReserveSnapshot> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/severity-reserve/build`, {
    method: "POST",
    credentials: "include",
  });
  return parse<SeverityReserveSnapshot>(response, "Severity & reserve support could not be refreshed");
}

export async function decideSeverityReserve(
  claimId: string,
  evaluationId: string,
  payload: SeverityReserveDecisionInput,
): Promise<SeverityReserveDecision> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/severity-reserve/evaluations/${evaluationId}/decision`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<SeverityReserveDecision>(response, "Severity & reserve support decision could not be recorded");
}
