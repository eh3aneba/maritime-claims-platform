import { API_BASE, ApiError } from "./api";

export type RecoveryDisposition = "pursue" | "monitor" | "do_not_pursue" | "close";
export type RecoveryActionType = "correspondence" | "demand" | "follow_up" | "response" | "note";
export type RecoveryActionDirection = "inbound" | "outbound" | "internal";
export type RecoveryContextState = "current" | "stale" | "reference_only" | "source_unavailable";

export interface RecoveryActionLog {
  id: string;
  decision_key: string;
  decision_id: string;
  created_by_id: string | null;
  action_number: number;
  action_type: RecoveryActionType;
  direction: RecoveryActionDirection;
  occurred_on: string;
  summary: string;
  source_reference: string;
  external_status: string | null;
  external_response_date: string | null;
  previous_action_hash: string | null;
  action_hash: string;
  created_at: string;
}

export interface RecoveryPursuitDecision {
  id: string;
  decision_key: string;
  version: number;
  supersedes_id: string | null;
  counterparty_id: string;
  counterparty_name: string;
  counterparty_role: string;
  decided_by_id: string | null;
  disposition: RecoveryDisposition;
  rationale: string;
  basis_reference: string;
  next_review_date: string | null;
  previous_decision_hash: string | null;
  decision_hash: string;
  context_state_status: RecoveryContextState;
  decided_at: string;
  actions: RecoveryActionLog[];
}

export interface RecoveryDecisionDashboard {
  claim_id: string;
  decisions: RecoveryPursuitDecision[];
  disclaimer: string;
}

export interface RecoveryPursuitDecisionInput {
  counterparty_id: string;
  disposition: RecoveryDisposition;
  rationale: string;
  basis_reference: string;
  next_review_date?: string | null;
}

export interface RecoveryActionLogInput {
  decision_hash: string;
  action_type: RecoveryActionType;
  direction: RecoveryActionDirection;
  occurred_on: string;
  summary: string;
  source_reference: string;
  external_status?: string | null;
  external_response_date?: string | null;
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

export async function getRecoveryDecisionDashboard(claimId: string): Promise<RecoveryDecisionDashboard> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/decisions`, {
    credentials: "include",
  });
  return parse<RecoveryDecisionDashboard>(response, "Recovery decisions could not be loaded");
}

export async function createRecoveryPursuitDecision(
  claimId: string,
  payload: RecoveryPursuitDecisionInput,
): Promise<RecoveryPursuitDecision> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/decisions`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<RecoveryPursuitDecision>(response, "Recovery decision could not be recorded");
}

export async function reviseRecoveryPursuitDecision(
  claimId: string,
  decisionKey: string,
  payload: RecoveryPursuitDecisionInput & { expected_decision_hash: string },
): Promise<RecoveryPursuitDecision> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/decisions/${decisionKey}/revisions`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<RecoveryPursuitDecision>(response, "Recovery decision revision could not be recorded");
}

export async function appendRecoveryAction(
  claimId: string,
  decisionKey: string,
  payload: RecoveryActionLogInput,
): Promise<RecoveryActionLog> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/decisions/${decisionKey}/actions`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<RecoveryActionLog>(response, "Recovery action could not be recorded");
}
