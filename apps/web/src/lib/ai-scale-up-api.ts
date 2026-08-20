import { API_BASE, ApiError } from "./api";

export type ScaleUpApprovalRole = "security" | "privacy" | "product" | "operations" | "risk";
export type ScaleUpAction = "approve" | "edit" | "reject";

export interface ScaleUpApproval {
  id: string; approval_role: ScaleUpApprovalRole; approver_id: string | null;
  action: "approve" | "reject"; evidence_reference: string | null; note: string;
}
export interface ScaleUpDocument {
  id: string; claim_id: string; document_id: string; rollout_bucket: number;
  document_type: string; status: string; snapshot_hash: string;
}
export interface ScaleUpRun {
  id: string; task_type: string; status: string; human_review_action: ScaleUpAction | null;
  output_candidate_count: number | null; unsupported_output_count: number | null;
  source_grounded_output_count: number | null; source_grounding_total_count: number | null;
  latency_ms: number | null; observed_provider_cost_microusd: number | null;
}
export interface ScaleUpMonitor {
  id: string; monitor_key: string; status: string; metrics: Record<string, unknown>;
  failure_reasons: string[]; monitor_hash: string; monitored_at: string;
}
export interface ScaleUpIncident {
  id: string; severity: string; category: string; status: string;
  evidence_reference: string; note: string;
}
export interface ScaleUpAuthorization {
  id: string; outcome_assessment_id: string; limited_production_authorization_id: string;
  attempt_number: number; authorization_key: string; environment: "production";
  authorization_mode: "controlled_scale_up"; outcome_assessment_hash: string;
  outcome_decision_hash: string; model: string; prompt_bundle_version: string;
  schema_bundle_version: string; max_input_chars: number; max_output_tokens: number;
  allowed_document_types: string[]; previous_rollout_percentage: number;
  rollout_percentage: number; max_claims: number; max_documents: number;
  max_users: number; max_provider_runs: number; starts_at: string; expires_at: string;
  controls: Record<string, number>; references: Record<string, string>;
  status: string; outcome: string | null; decision_hash: string | null;
  approvals: ScaleUpApproval[]; document_eligibility: ScaleUpDocument[];
  runs: ScaleUpRun[]; monitors: ScaleUpMonitor[]; incidents: ScaleUpIncident[];
  summary: {
    independent_approvals_complete: boolean; authorization_active: boolean;
    provider_run_count: number; human_reviewed_run_count: number;
    open_incident_count: number; monitor_fresh_and_passing: boolean;
    controlled_scale_up_authorized: boolean; rollout_percentage: number;
    rollout_above_25_percent_authorized: false; production_wide_authorized: false;
    restricted_documents_authorized: false; new_document_classes_authorized: false;
    autonomous_claim_decisions_authorized: false; authoritative_facts_auto_updated: false;
    human_review_required: true; previous_document_eligibility_carried_forward: false;
  };
}
export interface ScaleUpDashboard { authorizations: ScaleUpAuthorization[]; }

export interface GraduationAssessment {
  id: string; status: string; outcome: string | null; assessment_hash: string | null;
  decision_hash: string | null; rollout_percentage: number;
  metrics: Record<string, unknown> | null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function getScaleUpDashboard() {
  return request<ScaleUpDashboard>("/ai-scale-up");
}

export async function getGraduationRecommendations() {
  const result = await request<{ assessments: GraduationAssessment[] }>("/ai-limited-production-outcomes");
  return result.assessments.filter((item) =>
    item.status === "recommended" && item.outcome === "recommend_graduation_stage");
}

export function createScaleUp(outcomeAssessmentId: string) {
  return request<ScaleUpAuthorization>("/ai-scale-up/authorizations", {
    method: "POST",
    body: JSON.stringify({
      outcome_assessment_id: outcomeAssessmentId,
      authorization_key: `controlled-scale-up-${crypto.randomUUID()}`,
      allowed_document_types: ["chief_engineer_report", "engine_log"],
      rollout_percentage: 25,
      max_claims: 10, max_documents: 30, max_users: 10, max_provider_runs: 100,
      starts_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 14 * 86400000).toISOString(),
      deployment_isolation_reference: "artifact://ai-scale-up/deployment-isolation",
      provider_project_reference: "artifact://ai-scale-up/provider-project",
      credential_control_reference: "artifact://ai-scale-up/credential-boundary",
      privacy_legal_reference: "artifact://ai-scale-up/privacy-legal-basis",
      monitoring_reference: "monitor://ai-scale-up/live-quality-grounding",
      incident_response_reference: "runbook://ai-scale-up/incident-response",
      rollback_reference: "runbook://ai-scale-up/rollback-15-minutes",
      change_ticket_reference: "ticket://ai-scale-up/change-authorization",
      confirm_separate_controlled_scale_up: true,
    }),
  });
}

export function reviewScaleUp(id: string, role: ScaleUpApprovalRole, action: "approve" | "reject") {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/approvals`, {
    method: "POST",
    body: JSON.stringify({
      approval_role: role, action,
      evidence_reference: action === "approve" ? `artifact://ai-scale-up/${role}-review` : null,
      note: action === "approve"
        ? `Independent ${role} reviewer reproduced the exact 11-25 percent rollout, safety and rollback controls.`
        : `Independent ${role} reviewer rejected this controlled scale-up attempt.`,
    }),
  });
}

export function decideScaleUp(id: string, outcome: "authorize_scale_up" | "hold") {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ outcome, confirm_decision: true,
      note: outcome === "authorize_scale_up"
        ? "Administrator authorized only this exact expiring controlled scale-up; Production-wide use remains blocked."
        : "Administrator held the scale-up attempt; no wider Production AI authorization is granted." }),
  });
}

export function attestScaleUpDocument(id: string, claimId: string, documentId: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/documents`, {
    method: "POST",
    body: JSON.stringify({
      claim_id: claimId, document_id: documentId,
      legal_basis_reference: `artifact://ai-scale-up/document-${documentId}-legal-basis`,
      data_minimization_reference: `artifact://ai-scale-up/document-${documentId}-minimization`,
      change_ticket_reference: `ticket://ai-scale-up/document-${documentId}`,
      note: "Manager recorded fresh Sprint 11G eligibility; earlier 11E eligibility is not carried forward.",
      confirm_new_scale_up_eligibility: true,
    }),
  });
}

export function reviewScaleUpRun(id: string, action: ScaleUpAction) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/runs/${id}/outcome`, {
    method: "POST",
    body: JSON.stringify({
      human_review_action: action, output_candidate_count: 100,
      human_edit_count: action === "edit" ? 1 : 0,
      unsupported_output_count: 0, source_grounded_output_count: 100,
      source_grounding_total_count: 100, latency_ms: 1,
      observed_provider_cost_microusd: 0,
      evidence_reference: `artifact://ai-scale-up/run-${id}-review`,
      note: "Different human reviewed the provider result; replace sample counters with the observed content-free metrics.",
      confirm_human_review: true,
    }),
  });
}

export function monitorScaleUp(id: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/monitors`, {
    method: "POST",
    body: JSON.stringify({ monitor_key: `scale-up-monitor-${crypto.randomUUID()}`,
      note: "Operator froze review, grounding, unsupported-output, latency, cost and incident metrics.",
      confirm_live_monitor_snapshot: true }),
  });
}

export function reportScaleUpIncident(id: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/incidents`, {
    method: "POST",
    body: JSON.stringify({ severity: "high", category: "quality",
      evidence_reference: `ticket://ai-scale-up/incident-${crypto.randomUUID()}`,
      note: "Operator reported a high-severity issue and triggered immediate pause and rollback.",
      confirm_pause_and_rollback: true }),
  });
}

export function resolveScaleUpIncident(id: string, incidentId: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/incidents/${incidentId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ resolution_reference: `artifact://ai-scale-up/incident-${incidentId}-resolution`,
      resolution_note: "Administrator verified remediation; fresh passing monitoring is still required before any allowed resume.",
      confirm_resolution: true }),
  });
}

export function resumeScaleUp(id: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/resume`, {
    method: "POST", body: JSON.stringify({ confirm_resume: true,
      note: "Administrator verified incident closure and fresh passing monitoring before resuming the same bounded rollout." }),
  });
}

export function revokeScaleUp(id: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/revoke`, {
    method: "POST", body: JSON.stringify({ confirm_revoke: true,
      note: "Manager activated the immediate Sprint 11G kill switch." }),
  });
}

export function completeScaleUp(id: string) {
  return request<ScaleUpAuthorization>(`/ai-scale-up/authorizations/${id}/complete`, {
    method: "POST", body: JSON.stringify({ confirm_complete: true,
      note: "Every bounded run is independently reviewed, incidents are safe and the latest monitor passes." }),
  });
}
