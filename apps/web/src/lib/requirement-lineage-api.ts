import { API_BASE, ApiError } from "./api";

export interface EquivalentEvidenceAcceptancePayload {
  claim_fact_id: string;
  claim_fact_version: number;
  expected_state_fingerprint: string;
  expected_state_version: number;
  note: string;
  re_review?: boolean;
}

export interface RequirementDecisionResult {
  requirement: unknown;
  decision: unknown;
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
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Preserve a safe generic error for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<RequirementDecisionResult>;
}
