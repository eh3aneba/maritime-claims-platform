import { API_BASE, ApiError } from "./api";
import type { EvidenceRetrievalMode } from "./evidence-search-api";

export interface ClaimQaRequest {
  question: string;
  top_k?: number;
  retrieval_mode?: EvidenceRetrievalMode;
  include_superseded?: boolean;
  document_types?: string[];
  document_ids?: string[];
  exact_phrase?: boolean;
}

export interface ClaimQaSourceRef {
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
  source_file_hash: string;
  extraction_text_hash: string | null;
  normalized_text_hash: string;
  search_unit_hash: string;
}

export interface ClaimQaStatement {
  statement_number: number;
  text: string;
  source_refs: ClaimQaSourceRef[];
  statement_hash: string;
}

export interface ClaimQaConflict {
  conflict_type: "explicit_polarity" | "numeric_disagreement";
  detail: string;
  statement_hashes: string[];
}

export interface ClaimQaResponse {
  claim_id: string;
  status: "answered" | "insufficient_evidence" | "conflicting_evidence";
  answer: string;
  statements: ClaimQaStatement[];
  conflicts: ClaimQaConflict[];
  missing_evidence: string[];
  retrieval_run_id: string;
  retrieval_mode: EvidenceRetrievalMode;
  ranking_version: string;
  question_hash: string;
  result_set_hash: string;
  semantic_used: boolean;
  semantic_provider: string | null;
  semantic_model: string | null;
  semantic_authorization_hash: string | null;
  answer_engine_version: string;
  answer_hash: string;
  non_authoritative: boolean;
  human_review_required: boolean;
  claim_facts_updated: boolean;
  disclaimer: string;
}

async function parse<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    let detail = `${fallback} (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // Keep safe fallback for non-JSON failures.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function askClaimQuestion(
  claimId: string,
  payload: ClaimQaRequest,
): Promise<ClaimQaResponse> {
  const response = await fetch(`${API_BASE}/claims/${claimId}/evidence-search/qa`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ retrieval_mode: "hybrid", top_k: 5, ...payload }),
  });
  return parse<ClaimQaResponse>(response, "Claim Q&A could not be completed");
}
