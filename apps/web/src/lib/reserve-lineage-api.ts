import { API_BASE, ApiError } from "./api";

export type ReserveSourceKind = "manual" | "reserve_support" | "adjustment";

export interface ReserveHistoryEntry {
  id: string;
  amount: string;
  currency: string;
  reason: string;
  created_by_id: string | null;
  created_at: string;
  sequence: number | null;
  idempotency_key: string | null;
  source_kind: "legacy_unbound" | ReserveSourceKind;
  source_reference_id: string | null;
  source_state_hash: string | null;
  source_snapshot: Record<string, unknown>;
  previous_reserve_hash: string | null;
  reserve_hash: string | null;
}

export interface ReserveHistoryResponse {
  claim_id: string;
  currency: string;
  current_reserve: string | null;
  current_version: number;
  current_hash: string | null;
  items: ReserveHistoryEntry[];
}

export interface ReserveWritePayload {
  amount: string;
  reason: string;
  idempotency_key: string;
  expected_reserve_version: number;
  expected_reserve_hash: string | null;
  source_kind: ReserveSourceKind;
  source_reference_id: string | null;
}

async function reserveFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      // Preserve safe generic error for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function getAuthoritativeReserveHistory(claimId: string) {
  return reserveFetch<ReserveHistoryResponse>(`/claims/${claimId}/reserve-history`);
}

export function recordAuthoritativeReserve(claimId: string, payload: ReserveWritePayload) {
  return reserveFetch<Record<string, unknown>>(`/claims/${claimId}/reserve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
