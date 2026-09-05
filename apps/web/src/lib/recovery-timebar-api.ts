import { API_BASE, ApiError } from "./api";

export type RecoveryTimebarStatus = "triggered" | "not_triggered" | "insufficient_evidence" | "not_applicable";
export type RecoveryTimebarUrgency = "low" | "medium" | "high" | "critical";
export type RecoveryTimebarDecisionAction = "accept" | "edit" | "dismiss" | "not_applicable";
export type RecoverySourceState = "current" | "stale" | "reference_only" | "source_unavailable";
export type PeriodUnit = "days" | "months" | "years";
export type ScenarioReviewAction = "confirm" | "override" | "reject" | "review_needed";

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

export interface RecoveryCounterparty {
  id: string;
  counterparty_key: string;
  version: number;
  supersedes_id: string | null;
  created_by_id: string | null;
  name: string;
  role: string;
  allegation_basis: string;
  source_reference: string;
  source_document_id: string | null;
  source_document_family_id: string | null;
  source_document_version: number | null;
  source_document_hash: string | null;
  source_state_status: RecoverySourceState;
  record_hash: string;
  created_at: string;
}

export interface TimebarScenarioReview {
  id: string;
  scenario_id: string;
  reviewed_by_id: string | null;
  scenario_hash: string;
  review_number: number;
  action: ScenarioReviewAction;
  confirmed_deadline: string | null;
  note: string;
  source_reference: string | null;
  previous_review_hash: string | null;
  review_hash: string;
  reviewed_at: string;
}

export interface TimebarScenario {
  id: string;
  scenario_key: string;
  version: number;
  supersedes_id: string | null;
  created_by_id: string | null;
  counterparty_id: string | null;
  title: string;
  legal_basis: string;
  source_reference: string;
  source_document_id: string | null;
  source_document_family_id: string | null;
  source_document_version: number | null;
  source_document_hash: string | null;
  source_state_status: RecoverySourceState;
  anchor_date: string;
  period_value: number;
  period_unit: PeriodUnit;
  extension_value: number | null;
  extension_unit: PeriodUnit | null;
  extension_basis: string | null;
  assumptions: string;
  candidate_deadline: string;
  scenario_hash: string;
  created_at: string;
  latest_review: TimebarScenarioReview | null;
}

export interface RecoveryMaturityDashboard {
  claim_id: string;
  counterparties: RecoveryCounterparty[];
  scenarios: TimebarScenario[];
  disclaimer: string;
}

export interface RecoveryCounterpartyInput {
  name: string;
  role: string;
  allegation_basis: string;
  source_reference: string;
  source_document_id?: string | null;
}

export interface TimebarScenarioInput {
  title: string;
  legal_basis: string;
  source_reference: string;
  source_document_id?: string | null;
  counterparty_id?: string | null;
  anchor_date: string;
  period_value: number;
  period_unit: PeriodUnit;
  extension_value?: number | null;
  extension_unit?: PeriodUnit | null;
  extension_basis?: string | null;
  assumptions: string;
}

export interface TimebarScenarioReviewInput {
  action: ScenarioReviewAction;
  scenario_hash: string;
  confirmed_deadline?: string | null;
  note: string;
  source_reference?: string | null;
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

export async function getRecoveryMaturity(claimId: string): Promise<RecoveryMaturityDashboard> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/maturity`, { credentials: "include" });
  return parse<RecoveryMaturityDashboard>(response, "Recovery maturity workspace could not be loaded");
}

export async function createRecoveryCounterparty(
  claimId: string,
  payload: RecoveryCounterpartyInput,
): Promise<RecoveryCounterparty> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/counterparties`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<RecoveryCounterparty>(response, "Recovery counterparty could not be recorded");
}

export async function reviseRecoveryCounterparty(
  claimId: string,
  counterpartyKey: string,
  payload: RecoveryCounterpartyInput & { expected_record_hash: string },
): Promise<RecoveryCounterparty> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/counterparties/${counterpartyKey}/revisions`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<RecoveryCounterparty>(response, "Recovery counterparty revision could not be recorded");
}

export async function createTimebarScenario(claimId: string, payload: TimebarScenarioInput): Promise<TimebarScenario> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/scenarios`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<TimebarScenario>(response, "Time-bar scenario could not be created");
}

export async function reviseTimebarScenario(
  claimId: string,
  scenarioKey: string,
  payload: TimebarScenarioInput & { expected_scenario_hash: string },
): Promise<TimebarScenario> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/scenarios/${scenarioKey}/revisions`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<TimebarScenario>(response, "Time-bar scenario revision could not be created");
}

export async function reviewTimebarScenario(
  claimId: string,
  scenarioId: string,
  payload: TimebarScenarioReviewInput,
): Promise<TimebarScenarioReview> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/recovery-timebar/scenarios/${scenarioId}/review`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<TimebarScenarioReview>(response, "Time-bar scenario review could not be recorded");
}
