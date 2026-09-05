import { API_BASE, ApiError } from "@/lib/api";

export type AdjustmentStatus = "draft" | "under_review" | "approved" | "rejected";
export type AdjustmentTreatment = "pending" | "included" | "excluded" | "apportioned" | "credit";
export type AdjustmentBasis =
  | "unallocated"
  | "particular_average"
  | "general_average"
  | "sue_and_labour"
  | "rdc"
  | "other"
  | "not_applicable";
export type AdjustmentSourceState = "current" | "stale" | "legacy_unbound" | "source_unavailable";

export interface SourceGroundedControl {
  amount?: string | null;
  percentage?: string | null;
  basis: string;
  source_reference: string;
  computed_reference_amount?: string | null;
}

export interface FXControl {
  rate: string;
  source_currency: string;
  target_currency: string;
  rate_date: string;
  source_reference: string;
}

export interface LineFinancialControls {
  fx?: FXControl | null;
  tax?: SourceGroundedControl | null;
  depreciation?: SourceGroundedControl | null;
  betterment?: SourceGroundedControl | null;
  allocation?: SourceGroundedControl | null;
}

export interface MatureAdjustmentLine {
  id: string;
  statement_id: string;
  cost_item_id: string | null;
  source_document_id: string | null;
  sort_order: number;
  description: string;
  supplier: string | null;
  document_number: string | null;
  category: string | null;
  claimed_amount: string;
  considered_amount: string;
  treatment: AdjustmentTreatment;
  basis: AdjustmentBasis;
  reason: string | null;
  note: string | null;
  source_snapshot: Record<string, unknown>;
  financial_controls: LineFinancialControls;
  created_at: string;
  updated_at: string;
}

export interface AdjustmentSourceChangeSummary {
  added_item_keys: string[];
  removed_item_keys: string[];
  changed_item_keys: string[];
  added_count: number;
  removed_count: number;
  changed_count: number;
}

export interface MatureAdjustmentStatement {
  id: string;
  claim_id: string;
  created_by_id: string | null;
  reviewed_by_id: string | null;
  rebased_from_statement_id: string | null;
  version: number;
  title: string;
  currency: string;
  status: AdjustmentStatus;
  deductible_amount: string;
  deductible_basis: string | null;
  other_deduction_amount: string;
  other_deduction_basis: string | null;
  gross_claimed: string;
  gross_considered: string;
  net_adjusted: string;
  source_manifest: Array<Record<string, unknown>>;
  source_manifest_version: number;
  source_state_hash: string | null;
  current_source_state_hash: string | null;
  source_state_status: AdjustmentSourceState;
  source_change_summary: AdjustmentSourceChangeSummary;
  review_note: string | null;
  content_hash: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  lines: MatureAdjustmentLine[];
}

export interface MatureAdjustmentListResponse {
  items: MatureAdjustmentStatement[];
  total: number;
}

export interface AdjustmentLineUpdatePayload {
  treatment: AdjustmentTreatment;
  basis: AdjustmentBasis;
  considered_amount: string;
  claimed_amount?: string;
  financial_controls?: LineFinancialControls;
  reason?: string | null;
  note?: string | null;
}

async function adjustmentFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      // Keep safe fallback when the server response is not JSON.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function listMatureAdjustments(claimId: string) {
  return adjustmentFetch<MatureAdjustmentListResponse>(`/claims/${claimId}/adjustments`);
}

export function createMatureAdjustment(claimId: string, payload: { currency: string; title?: string | null }) {
  return adjustmentFetch<MatureAdjustmentStatement>(`/claims/${claimId}/adjustments`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateMatureAdjustment(
  claimId: string,
  statementId: string,
  payload: Partial<{
    title: string;
    deductible_amount: string;
    deductible_basis: string;
    other_deduction_amount: string;
    other_deduction_basis: string;
  }>,
) {
  return adjustmentFetch<MatureAdjustmentStatement>(`/claims/${claimId}/adjustments/${statementId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function updateMatureAdjustmentLine(
  claimId: string,
  statementId: string,
  lineId: string,
  payload: AdjustmentLineUpdatePayload,
) {
  return adjustmentFetch<MatureAdjustmentStatement>(
    `/claims/${claimId}/adjustments/${statementId}/lines/${lineId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function rebaseMatureAdjustment(
  claimId: string,
  statementId: string,
  payload: { carry_statement_controls: boolean; note: string },
) {
  return adjustmentFetch<MatureAdjustmentStatement>(`/claims/${claimId}/adjustments/${statementId}/rebase`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function submitMatureAdjustment(claimId: string, statementId: string) {
  return adjustmentFetch<MatureAdjustmentStatement>(`/claims/${claimId}/adjustments/${statementId}/submit`, {
    method: "POST",
  });
}

export function reviewMatureAdjustment(
  claimId: string,
  statementId: string,
  action: "approve" | "reject",
  note: string,
) {
  return adjustmentFetch<MatureAdjustmentStatement>(
    `/claims/${claimId}/adjustments/${statementId}/${action}`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}
