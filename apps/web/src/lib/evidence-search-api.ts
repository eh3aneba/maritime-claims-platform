import { API_BASE, ApiError } from "./api";

export interface EvidenceSearchRequest {
  query: string;
  top_k?: number;
  retrieval_mode?: "lexical";
  include_superseded?: boolean;
  document_types?: string[];
  document_ids?: string[];
  exact_phrase?: boolean;
}

export interface EvidenceSearchResult {
  search_unit_id: string;
  segment_id: string;
  document_id: string;
  extraction_id: string;
  document_family_id: string;
  document_filename: string;
  document_type: string | null;
  document_version: number;
  is_current_document: boolean;
  locator_type: string;
  locator_value: string;
  confidentiality_level: string;
  snippet: string;
  lexical_score: number;
  semantic_score: number | null;
  combined_score: number;
  match_reasons: string[];
  source_file_hash: string;
  extraction_text_hash: string | null;
  normalized_text_hash: string;
  search_unit_hash: string;
}

export interface EvidenceSearchResponse {
  claim_id: string;
  run_id: string;
  retrieval_mode: string;
  ranking_version: string;
  query_hash: string;
  filters_hash: string;
  result_set_hash: string;
  result_count: number;
  no_sufficient_evidence_found: boolean;
  results: EvidenceSearchResult[];
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

export async function searchClaimEvidence(
  claimId: string,
  payload: EvidenceSearchRequest,
): Promise<EvidenceSearchResponse> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/evidence-search`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ retrieval_mode: "lexical", top_k: 10, ...payload }),
  });
  return parse<EvidenceSearchResponse>(response, "Evidence search could not be completed");
}

export async function downloadEvidenceSearchDocument(
  claimId: string,
  documentId: string,
  filename: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/documents/${documentId}/download`, {
    credentials: "include",
  });
  if (!response.ok) {
    let detail = `Source document could not be downloaded (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // Keep safe fallback.
    }
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
