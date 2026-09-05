import { API_BASE, ApiError } from "@/lib/api";

export type CostReviewStatus =
  | "claimed"
  | "under_review"
  | "potentially_recoverable"
  | "potentially_non_recoverable"
  | "accepted"
  | "rejected"
  | "paid";

export type CostDecisionState = "none" | "current" | "stale";

export interface CostReviewDecision {
  id: string;
  item_key: string;
  state_fingerprint: string;
  state_version: number;
  decision_number: number;
  status: CostReviewStatus;
  reason: string;
  item_snapshot: Record<string, unknown>;
  reviewed_by_id: string | null;
  reviewed_at: string;
  previous_decision_hash: string | null;
  decision_hash: string;
}

export interface MatureFinancialCostItem {
  id: string;
  document_id: string;
  document_family_id: string;
  document_version: number;
  document_is_current: boolean;
  document_processing_status: string;
  document_malware_scan_status: string;
  source_state: "current_usable";
  document_kind: string;
  supplier: string | null;
  document_number: string | null;
  document_date: string | null;
  line_index: number;
  description: string;
  quantity: string | null;
  unit: string | null;
  unit_price: string | null;
  amount: string;
  currency: string;
  category: string | null;
  review_status: CostReviewStatus;
  item_key: string;
  state_fingerprint: string;
  state_version: number;
  decision_state: CostDecisionState;
  latest_review_decision: CostReviewDecision | null;
  review_history: CostReviewDecision[];
}

export interface HistoricalCostReview {
  item_key: string;
  decision_state: "stale";
  current_source_available: false;
  latest_review_decision: CostReviewDecision;
  message: string;
}

export interface FinancialFlag {
  id: string;
  flag_type: string;
  severity: string;
  title: string;
  explanation: string;
  evidence: Record<string, unknown> | null;
  status: "open" | "explained" | "resolved" | "irrelevant";
  resolution_note: string | null;
}

export interface QuoteComparisonRow {
  document_id: string;
  document_version: number;
  supplier: string | null;
  quotation_number: string | null;
  currency: string | null;
  total: string | null;
  scope_summary: string | null;
  lead_time: string | null;
  repair_duration: string | null;
  line_items: Array<Record<string, unknown>>;
}

export interface ReserveHistoryRow {
  id: string;
  amount: string;
  currency: string;
  reason: string;
  created_by_id: string | null;
  created_at: string;
}

export interface MatureFinancialReviewResponse {
  claim_id: string;
  totals_by_currency: Record<string, string>;
  items: MatureFinancialCostItem[];
  flags: FinancialFlag[];
  quotations: QuoteComparisonRow[];
  reserve_history: ReserveHistoryRow[];
  historical_reviews: HistoricalCostReview[];
  summary: {
    current_item_count: number;
    current_decision_count: number;
    stale_decision_count: number;
    unreviewed_item_count: number;
  };
}

export interface CostReviewDecisionPayload {
  status: CostReviewStatus;
  reason: string;
  expected_state_fingerprint: string;
  expected_state_version: number;
  confirm_re_review: boolean;
}

async function financialFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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

export function getMatureFinancialReview(claimId: string) {
  return financialFetch<MatureFinancialReviewResponse>(`/claims/${claimId}/financial-review`);
}

export function recordCostReviewDecision(
  claimId: string,
  itemId: string,
  payload: CostReviewDecisionPayload,
) {
  return financialFetch<CostReviewDecision>(
    `/claims/${claimId}/financial-review/items/${itemId}/status`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
