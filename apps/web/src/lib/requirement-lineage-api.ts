import { API_BASE, ApiError } from "./api";

export interface EquivalentEvidenceAcceptancePayload {
  claim_fact_id: string;
  claim_fact_version: number;
  expected_state_fingerprint: string;
  expected_state_version: number;
  note: string;
  re_review?: boolean;
}

export interface RequirementDecision {
  id: string;
  requirement_id: string;
  decided_by_id: string | null;
  claim_fact_id: string | null;
  state_fingerprint: string;
  state_version: number;
  decision_number: number;
  action: string;
  note: string;
  claim_fact_version: number | null;
  source_document_id: string | null;
  source_document_version: number | null;
  previous_decision_hash: string | null;
  decision_hash: string;
  decided_at: string;
}

export interface RequirementDecisionHistory {
  requirement_id: string;
  state_fingerprint: string;
  state_version: number;
  items: RequirementDecision[];
}

export interface RequirementDecisionResult {
  requirement: unknown;
  decision: unknown;
}

async function responseDetail(response: Response) {
  let detail = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // Preserve a safe generic error for non-JSON failures.
  }
  return detail;
}

export async function getRequirementDecisionHistory(
  claimId: string,
  requirementId: string,
): Promise<RequirementDecisionHistory> {
  const response = await fetch(
    `${API_BASE}/claims/${claimId}/rules/requirements/${requirementId}/decisions`,
    { credentials: "include" },
  );

  if (!response.ok) {
    throw new ApiError(response.status, await responseDetail(response));
  }

  return response.json() as Promise<RequirementDecisionHistory>;
}

export async function acceptRequirementEquivalentEvidence(
  claimId: string,
  requirementId: string,
  payload: EquivalentEvidenceAcceptancePayload,
): Promise<RequirementDecisionResult> {
  const response = await fetch(
    `${API_BASE}/claims/${claimId}/rules/requirements/${requirementId}/accept-equivalent`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok) {
    throw new ApiError(response.status, await responseDetail(response));
  }

  return response.json() as Promise<RequirementDecisionResult>;
}
