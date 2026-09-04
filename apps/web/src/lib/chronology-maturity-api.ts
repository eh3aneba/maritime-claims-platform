import { API_BASE, ApiError } from "./api";
import type { ClaimChronologyResponse, EvidenceConflict, EvidenceConflictStatus } from "./types";

export type ConflictDecisionState = "none" | "current" | "stale";

export interface ConflictDecisionHistoryItem {
  id: string;
  state_fingerprint: string;
  state_version: number;
  decision_number: number;
  status: EvidenceConflictStatus;
  note: string;
  decided_by_id: string | null;
  decided_at: string;
  previous_decision_hash: string | null;
  decision_hash: string;
  created_at: string;
}

export type MatureEvidenceConflict = EvidenceConflict & {
  state_fingerprint: string | null;
  state_version: number;
  decision_state: ConflictDecisionState;
  decision_history: ConflictDecisionHistoryItem[];
};

export type MatureClaimChronologyResponse = Omit<ClaimChronologyResponse, "conflicts"> & {
  conflicts: MatureEvidenceConflict[];
};

export interface StateAwareConflictResolutionPayload {
  status: Exclude<EvidenceConflictStatus, "open">;
  note: string;
  expected_state_fingerprint: string;
  expected_state_version: number;
  confirm_re_review: boolean;
}

export interface StateAwareConflictResolutionResponse {
  id: string;
  status: EvidenceConflictStatus;
  resolution_note: string | null;
  resolved_by_id: string | null;
  resolved_at: string | null;
  state_fingerprint: string;
  state_version: number;
  decision_number: number;
  decision_hash: string;
  replayed: boolean;
}

export async function resolveEvidenceConflictStateAware(
  claimId: string,
  conflictId: string,
  payload: StateAwareConflictResolutionPayload,
): Promise<StateAwareConflictResolutionResponse> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/chronology/conflicts/${conflictId}/resolve`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body && typeof body.detail !== "undefined") detail = String(body.detail);
    } catch {
      // Keep the status-based fallback when an intermediary returns a non-JSON body.
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<StateAwareConflictResolutionResponse>;
}
