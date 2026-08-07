import type { AIReviewDetail, AIReviewQueueResponse, AIReviewResult, AISourcePreview, Claim, ClaimDocument, ClaimFactListResponse, ClaimListResponse, CurrentUser, DocumentListResponse, EngineLogEventsResponse, ClaimChronologyResponse, ClaimRuleSummary, ClaimTaskListResponse, DocumentRequestResult, Vessel, VesselListResponse } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      // Keep a safe generic error for non-JSON responses.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function login(payload: { organization_slug: string; email: string; password: string }) {
  return apiFetch<{ access_token: string; token_type: string; user: CurrentUser }>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function logout() {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}

export function getCurrentUser() {
  return apiFetch<CurrentUser>("/auth/me");
}

export function listClaims(params?: URLSearchParams) {
  const query = params?.toString();
  return apiFetch<ClaimListResponse>(`/claims${query ? `?${query}` : ""}`);
}

export function getClaim(id: string) {
  return apiFetch<Claim>(`/claims/${id}`);
}

export function createClaim(payload: {
  vessel_id: string;
  incident_date: string;
  notification_date: string;
  incident_description: string;
  claim_type: "hull_machinery";
  claim_subtype: "machinery_damage";
  priority: "low" | "medium" | "high" | "critical";
  external_reference?: string | null;
  estimated_loss?: number | null;
  currency: string;
}) {
  return apiFetch<Claim>("/claims", { method: "POST", body: JSON.stringify(payload) });
}

export function updateClaim(id: string, payload: Partial<{
  incident_date: string;
  notification_date: string;
  incident_description: string;
  external_reference: string | null;
  estimated_loss: number | null;
  currency: string;
  priority: "low" | "medium" | "high" | "critical";
}>) {
  return apiFetch<Claim>(`/claims/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function changeClaimStatus(id: string, status: string, reason?: string) {
  return apiFetch<Claim>(`/claims/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ status, reason: reason || null }),
  });
}

export function changeClaimReserve(id: string, amount: number, reason: string) {
  return apiFetch<Claim>(`/claims/${id}/reserve`, {
    method: "POST",
    body: JSON.stringify({ amount, reason }),
  });
}

export function listVessels(search?: string) {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  return apiFetch<VesselListResponse>(`/vessels${query}`);
}

export function createVessel(payload: {
  name: string;
  imo_number?: string | null;
  vessel_type?: string | null;
  flag?: string | null;
}) {
  return apiFetch<Vessel>("/vessels", { method: "POST", body: JSON.stringify(payload) });
}
export function listClaimDocuments(claimId: string) {
  return apiFetch<DocumentListResponse>(`/claims/${claimId}/documents`);
}

export function deleteClaimDocument(claimId: string, documentId: string) {
  return apiFetch<void>(`/claims/${claimId}/documents/${documentId}`, { method: "DELETE" });
}

export async function downloadClaimDocument(claimId: string, document: ClaimDocument) {
  const response = await fetch(`${API_BASE}/claims/${claimId}/documents/${document.id}/download`, {
    credentials: "include",
  });
  if (!response.ok) {
    let detail = `Download failed (${response.status})`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement("a");
  anchor.href = url;
  anchor.download = document.original_filename;
  window.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function uploadClaimDocument(
  claimId: string,
  file: File,
  options: { documentType?: string; confidentiality?: "internal" | "confidential" | "restricted" } = {},
  onProgress?: (percent: number) => void,
): Promise<ClaimDocument> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    if (options.documentType) form.append("document_type", options.documentType);
    form.append("confidentiality_level", options.confidentiality ?? "confidential");

    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE}/claims/${claimId}/documents`);
    request.withCredentials = true;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onerror = () => reject(new ApiError(0, "Upload failed because the network request could not be completed."));
    request.onload = () => {
      let payload: unknown = null;
      try { payload = request.responseText ? JSON.parse(request.responseText) : null; } catch {}
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as ClaimDocument);
        return;
      }
      const detail = typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `Upload failed (${request.status})`;
      reject(new ApiError(request.status, detail));
    };
    request.send(form);
  });
}


export function listAIReview(params?: URLSearchParams) {
  const query = params?.toString();
  return apiFetch<AIReviewQueueResponse>(`/ai-review${query ? `?${query}` : ""}`);
}

export function reviewAIExtraction(
  extractionId: string,
  payload: { action: "approve" | "edit" | "reject"; value?: unknown; reason?: string },
) {
  return apiFetch<AIReviewResult>(`/ai-review/${extractionId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function bulkApproveAIExtractions(extractionIds: string[], reason?: string) {
  return apiFetch<{ reviewed: AIReviewResult[] }>("/ai-review/bulk/approve", {
    method: "POST",
    body: JSON.stringify({ extraction_ids: extractionIds, reason: reason || null }),
  });
}

export function getAISourcePreview(extractionId: string) {
  return apiFetch<AISourcePreview>(`/ai-review/${extractionId}/source`);
}

export function getClaimFacts(claimId: string) {
  return apiFetch<ClaimFactListResponse>(`/claims/${claimId}/facts`);
}

export function getAIReviewDetail(extractionId: string) {
  return apiFetch<AIReviewDetail>(`/ai-review/${extractionId}`);
}

export function runDocumentIntelligence(
  claimId: string,
  documentId: string,
  type: "ce-report" | "engine-log",
) {
  return apiFetch<{ job_id: string; status: string }>(
    `/claims/${claimId}/documents/${documentId}/intelligence/${type}`,
    { method: "POST" },
  );
}

export function getEngineLogEvents(claimId: string, documentId: string) {
  return apiFetch<EngineLogEventsResponse>(
    `/claims/${claimId}/documents/${documentId}/intelligence/engine-log/events`,
  );
}


export function getClaimChronology(claimId: string) {
  return apiFetch<ClaimChronologyResponse>(`/claims/${claimId}/chronology`);
}

export function rebuildClaimChronology(claimId: string) {
  return apiFetch<{ events_created_or_activated: number; conflicts_created_or_activated: number; event_count: number; open_conflict_count: number }>(
    `/claims/${claimId}/chronology/rebuild`,
    { method: "POST" },
  );
}

export function resolveEvidenceConflict(
  claimId: string,
  conflictId: string,
  payload: { status: "explained" | "resolved" | "accepted_difference" | "irrelevant"; note: string },
) {
  return apiFetch<{ id: string; status: string; resolution_note: string | null; resolved_by_id: string | null; resolved_at: string | null }>(
    `/claims/${claimId}/chronology/conflicts/${conflictId}/resolve`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}


export function getClaimRules(claimId: string) {
  return apiFetch<ClaimRuleSummary>(`/claims/${claimId}/rules`);
}

export function evaluateClaimRules(claimId: string) {
  return apiFetch<{ run_id: string; summary: ClaimRuleSummary }>(`/claims/${claimId}/rules/evaluate`, { method: "POST" });
}


export function listClaimTasks(claimId: string) {
  return apiFetch<ClaimTaskListResponse>(`/claims/${claimId}/tasks`);
}

export function createDocumentRequest(claimId: string, payload: { requirement_ids?: string[]; all_critical?: boolean; due_date?: string | null; recipient_label?: string | null; assignee_id?: string | null }) {
  return apiFetch<DocumentRequestResult>(`/claims/${claimId}/document-requests`, { method: "POST", body: JSON.stringify(payload) });
}

export function completeClaimTask(claimId: string, taskId: string, reason: string) {
  return apiFetch(`/claims/${claimId}/tasks/${taskId}/complete`, { method: "POST", body: JSON.stringify({ reason }) });
}

export function markDocumentRequestSent(claimId: string, batchId: string) {
  return apiFetch(`/claims/${claimId}/document-requests/${batchId}/mark-sent`, { method: "POST" });
}
