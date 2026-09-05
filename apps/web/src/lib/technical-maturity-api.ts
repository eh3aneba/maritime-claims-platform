import { API_BASE, ApiError } from "@/lib/api";

export type TechnicalDecisionAction =
  | "keep_open"
  | "supported_for_investigation"
  | "not_supported"
  | "needs_more_evidence";

export type TechnicalDecisionState = "none" | "current" | "stale";

export interface TechnicalEvidenceItem {
  extraction_id: string | null;
  field_path: string;
  value: unknown;
  document_id: string | null;
  document_version: number | null;
  document_is_current: boolean | null;
  document_processing_status: string | null;
  document_malware_scan_status: string | null;
  source_state: string | null;
  source_quote: string | null;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_verified: boolean | null;
}

export interface TechnicalInvestigationDecision {
  id: string;
  topic_key: string;
  topic_kind: string;
  state_fingerprint: string;
  state_version: number;
  decision_number: number;
  action: TechnicalDecisionAction;
  note: string;
  decided_by_id: string | null;
  decided_at: string;
  previous_decision_hash: string | null;
  decision_hash: string;
}

export interface MatureTechnicalMatrixRow {
  key: string;
  topic_kind: string;
  title: string;
  severity: string;
  status: string;
  evidence_for: unknown[];
  evidence_against: unknown[];
  unknown_or_missing: string[];
  recommended_follow_up: string[];
  explanation: string;
  state_fingerprint: string;
  state_version: number;
  decision_state: TechnicalDecisionState;
  latest_decision: TechnicalInvestigationDecision | null;
}

export interface MatureTechnicalReviewResponse {
  maintenance_facts: Record<string, unknown>;
  workshop_findings: TechnicalEvidenceItem[];
  workshop_repair_options: TechnicalEvidenceItem[];
  workshop_cause_opinions: TechnicalEvidenceItem[];
  matrix: MatureTechnicalMatrixRow[];
  generated_at: string;
}

export interface TechnicalDecisionHistoryResponse {
  topic_key: string;
  current_state_fingerprint: string | null;
  current_state_version: number | null;
  decision_state: TechnicalDecisionState;
  items: TechnicalInvestigationDecision[];
}

export interface TechnicalDecisionPayload {
  action: TechnicalDecisionAction;
  note: string;
  expected_state_fingerprint: string;
  expected_state_version: number;
  confirm_re_review: boolean;
}

async function technicalFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch {
      // Preserve a safe generic error for non-JSON responses.
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

export function getMatureTechnicalReview(claimId: string) {
  return technicalFetch<MatureTechnicalReviewResponse>(`/claims/${claimId}/technical-review`);
}

export function getTechnicalDecisionHistory(claimId: string, topicKey: string) {
  return technicalFetch<TechnicalDecisionHistoryResponse>(
    `/claims/${claimId}/technical-review/topics/${encodeURIComponent(topicKey)}/decisions`,
  );
}

export function recordTechnicalDecision(
  claimId: string,
  topicKey: string,
  payload: TechnicalDecisionPayload,
) {
  return technicalFetch<TechnicalInvestigationDecision>(
    `/claims/${claimId}/technical-review/topics/${encodeURIComponent(topicKey)}/decisions`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
