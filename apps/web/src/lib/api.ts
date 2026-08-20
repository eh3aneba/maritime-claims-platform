import type { AIReviewDetail, AIReviewGroupQueueResponse, AIReviewQueueResponse, AIReviewResult, AISourcePreview, Claim, ClaimDocument, ClaimDocumentRequirement, ClaimFactListResponse, ClaimListResponse, CurrentUser, DocumentListResponse, EngineLogEventsResponse, ClaimChronologyResponse, ClaimRuleSummary, ClaimTaskListResponse, DocumentRequestResult, Vessel, VesselListResponse, TechnicalReviewResponse, FinancialReviewResponse, CostReviewStatus, LegacyRescanResponse, QuarantineRetryResponse, ClaimIntakeApprovalResult, ClaimIntakeDraft } from "./types";
import type { EvidenceMatrixResponse } from "./types";

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

export async function uploadClaimIntakeDraft(file: File): Promise<ClaimIntakeDraft> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/claim-intake/drafts`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  if (!response.ok) {
    let detail = `Intake upload failed (${response.status})`;
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<ClaimIntakeDraft>;
}

export function getClaimIntakeDraft(id: string) {
  return apiFetch<ClaimIntakeDraft>(`/claim-intake/drafts/${id}`);
}

export function approveClaimIntakeDraft(
  id: string,
  payload: {
    claim: {
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
    };
    document_type: string;
    review_note: string;
  },
) {
  return apiFetch<ClaimIntakeApprovalResult>(`/claim-intake/drafts/${id}/approve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rejectClaimIntakeDraft(id: string, reason: string) {
  return apiFetch<ClaimIntakeDraft>(`/claim-intake/drafts/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
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

export function replaceClaimDocument(
  claimId: string,
  documentId: string,
  file: File,
  replacementReason: string,
  onProgress?: (percent: number) => void,
): Promise<ClaimDocument> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("replacement_reason", replacementReason);

    const request = new XMLHttpRequest();
    request.open(
      "POST",
      `${API_BASE}/claims/${claimId}/documents/${documentId}/replacements`,
    );
    request.withCredentials = true;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onerror = () => reject(
      new ApiError(0, "Replacement failed because the network request could not be completed."),
    );
    request.onload = () => {
      let payload: unknown = null;
      try { payload = request.responseText ? JSON.parse(request.responseText) : null; } catch {}
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as ClaimDocument);
        return;
      }
      const detail = typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `Replacement failed (${request.status})`;
      reject(new ApiError(request.status, detail));
    };
    request.send(form);
  });
}

export function queueLegacyEvidenceRescan(claimId: string, limit = 10) {
  return apiFetch<LegacyRescanResponse>(`/claims/${claimId}/documents/rescan-legacy`, {
    method: "POST",
    body: JSON.stringify({ limit }),
  });
}

export function retryQuarantinedUpload(claimId: string, uploadId: string) {
  return apiFetch<QuarantineRetryResponse>(
    `/claims/${claimId}/documents/quarantined-uploads/${uploadId}/retry`,
    { method: "POST" },
  );
}

export function purgeQuarantinedUpload(
  claimId: string,
  uploadId: string,
  reason: string,
) {
  return apiFetch<{ quarantine_id: string; status: "purged" }>(
    `/claims/${claimId}/documents/quarantined-uploads/${uploadId}/purge`,
    {
      method: "POST",
      body: JSON.stringify({ confirm_upload_id: uploadId, reason }),
    },
  );
}


export function listAIReview(params?: URLSearchParams) {
  const query = params?.toString();
  return apiFetch<AIReviewQueueResponse>(`/ai-review${query ? `?${query}` : ""}`);
}

export function listAIReviewGroups(params?: URLSearchParams) {
  const query = params?.toString();
  return apiFetch<AIReviewGroupQueueResponse>(`/ai-review/groups${query ? `?${query}` : ""}`);
}

export function reviewAIGroup(extractionIds: string[], action: "approve" | "reject", reason?: string) {
  return apiFetch<{ reviewed: AIReviewResult[] }>("/ai-review/groups/review", {
    method: "POST",
    body: JSON.stringify({ extraction_ids: extractionIds, action, reason: reason || null }),
  });
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
  type: "ce-report" | "engine-log" | "running-hours" | "pms-history" | "workshop-report" | "quotation" | "invoice",
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

export function acceptEquivalentEvidence(claimId: string, requirementId: string, claimFactId: string, note: string) {
  return apiFetch<{ requirement: ClaimDocumentRequirement }>(`/claims/${claimId}/rules/requirements/${requirementId}/accept-equivalent`, {
    method: "POST",
    body: JSON.stringify({ claim_fact_id: claimFactId, note }),
  });
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

export function getTechnicalReview(claimId: string) {
  return apiFetch<TechnicalReviewResponse>(`/claims/${claimId}/technical-review`);
}

export function getFinancialReview(claimId: string) { return apiFetch<FinancialReviewResponse>(`/claims/${claimId}/financial-review`); }
export function updateCostStatus(claimId:string,itemId:string,status:CostReviewStatus,reason:string){ return apiFetch(`/claims/${claimId}/financial-review/items/${itemId}/status`,{method:"POST",body:JSON.stringify({status,reason})}); }
export function resolveFinancialFlag(claimId:string,flagId:string,status:"explained"|"resolved"|"irrelevant",note:string){ return apiFetch(`/claims/${claimId}/financial-review/flags/${flagId}/resolve`,{method:"POST",body:JSON.stringify({status,note})}); }

export function getInitialAssessment(claimId: string) {
  return apiFetch<import("./types").InitialAssessment | null>(`/claims/${claimId}/initial-assessment`);
}

export function generateInitialAssessment(claimId: string, payload: { allow_if_not_ready: boolean; override_reason?: string | null }) {
  return apiFetch<import("./types").InitialAssessment>(`/claims/${claimId}/initial-assessment/generate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reviewAssessmentSection(claimId: string, sectionId: string, payload: { action: "approve" | "edit"; text?: string | null }) {
  return apiFetch<import("./types").AssessmentSection>(`/claims/${claimId}/initial-assessment/sections/${sectionId}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function approveInitialAssessment(claimId: string, assessmentId: string, note?: string) {
  return apiFetch<import("./types").InitialAssessment>(`/claims/${claimId}/initial-assessment/${assessmentId}/approve`, {
    method: "POST",
    body: JSON.stringify({ note: note || null }),
  });
}

export function startPilotSession(payload: { claim_id: string; participant_role?: string; objective?: string | null; baseline_assessment_minutes?: number | null }) {
  return apiFetch<import("./types").PilotSession>("/pilot/sessions", { method: "POST", body: JSON.stringify(payload) });
}

export function endPilotSession(sessionId: string, status: "completed" | "abandoned" = "completed", note?: string) {
  return apiFetch<import("./types").PilotSession>(`/pilot/sessions/${sessionId}/end`, { method: "POST", body: JSON.stringify({ status, note: note || null }) });
}

export function addPilotFeedback(sessionId: string, payload: { category: string; severity: string; verdict?: string | null; rating?: number | null; comment: string; entity_type?: string | null; entity_id?: string | null }) {
  return apiFetch(`/pilot/sessions/${sessionId}/feedback`, { method: "POST", body: JSON.stringify(payload) });
}

export function getPilotScorecard(sessionId: string) {
  return apiFetch<import("./types").PilotScorecard>(`/pilot/sessions/${sessionId}/scorecard`);
}

export function recordPilotBrowserEvent(sessionId: string, payload: { event_type: string; duration_ms?: number; event_data?: Record<string, unknown> }) {
  return apiFetch(`/pilot/sessions/${sessionId}/events`, { method: "POST", body: JSON.stringify(payload) });
}

export function getPilotCommercialValidation(sessionId: string) {
  return apiFetch<import("./types").PilotCommercialValidation | null>(`/pilot/sessions/${sessionId}/commercial-validation`);
}

export function savePilotCommercialValidation(sessionId: string, payload: Record<string, unknown>) {
  return apiFetch<import("./types").PilotCommercialValidation>(`/pilot/sessions/${sessionId}/commercial-validation`, { method: "PUT", body: JSON.stringify(payload) });
}

export function getPilotCommercialScorecard(sessionId: string) {
  return apiFetch<import("./types").PilotCommercialScorecard>(`/pilot/sessions/${sessionId}/commercial-scorecard`);
}

export function getDesignPartnerCohort() {
  return apiFetch<import("./types").DesignPartnerCohortSummary>("/outreach/cohort");
}
export function createDesignPartnerAccount(payload: Record<string, unknown>) {
  return apiFetch<import("./types").DesignPartnerAccount>("/outreach/accounts", { method: "POST", body: JSON.stringify(payload) });
}
export function updateDesignPartnerAccount(accountId: string, payload: Record<string, unknown>) {
  return apiFetch<import("./types").DesignPartnerAccount>(`/outreach/accounts/${accountId}`, { method: "PATCH", body: JSON.stringify(payload) });
}


export function getEvidenceMatrix(claimId: string) {
  return apiFetch<EvidenceMatrixResponse>(`/claims/${claimId}/evidence-matrix`);
}


export function listClaimPackExports(claimId: string) {
  return apiFetch<import("./types").ClaimPackExportListResponse>(
    "/claims/" + claimId + "/claim-pack-exports",
  );
}

export function generateClaimPackExport(
  claimId: string,
  payload: {
    export_format: import("./types").ClaimPackFormat;
    acknowledge_review_aid: boolean;
    generation_note?: string | null;
  },
) {
  return apiFetch<import("./types").ClaimPackExport>(
    "/claims/" + claimId + "/claim-pack-exports",
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function downloadClaimPackExport(
  claimId: string,
  item: import("./types").ClaimPackExport,
) {
  const response = await fetch(
    API_BASE +
      "/claims/" +
      claimId +
      "/claim-pack-exports/" +
      item.id +
      "/download",
    { credentials: "include" },
  );
  if (!response.ok) {
    let detail = "Claim-pack download failed (" + response.status + ")";
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = item.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}


export function getPolicyIntelligence(claimId: string) {
  return apiFetch<import("./types").PolicyIntelligenceResponse>(
    "/claims/" + claimId + "/policy-intelligence",
  );
}

export function extractPolicyTerms(claimId: string, documentId: string) {
  return apiFetch<import("./types").PolicyExtractionResponse>(
    "/claims/" +
      claimId +
      "/policy-intelligence/documents/" +
      documentId +
      "/extract",
    { method: "POST" },
  );
}

export function listClaimCorrespondence(claimId: string) {
  return apiFetch<import("./types").CorrespondenceListResponse>("/claims/" + claimId + "/correspondence");
}

export function createClaimCorrespondence(claimId: string, payload: {
  direction: import("./types").CorrespondenceDirection;
  kind: import("./types").CorrespondenceKind;
  sensitivity: import("./types").CorrespondenceSensitivity;
  sender_label?: string | null;
  recipient_label?: string | null;
  subject: string;
  body: string;
  channel?: import("./types").CorrespondenceChannel | null;
  external_reference?: string | null;
}) {
  return apiFetch<import("./types").ClaimCorrespondence>("/claims/" + claimId + "/correspondence", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function updateClaimCorrespondence(claimId: string, itemId: string, payload: Partial<{
  kind: import("./types").CorrespondenceKind;
  sensitivity: import("./types").CorrespondenceSensitivity;
  sender_label: string | null;
  recipient_label: string | null;
  subject: string;
  body: string;
}>) {
  return apiFetch<import("./types").ClaimCorrespondence>("/claims/" + claimId + "/correspondence/" + itemId, {
    method: "PATCH", body: JSON.stringify(payload),
  });
}

export function submitClaimCorrespondence(claimId: string, itemId: string) {
  return apiFetch<import("./types").ClaimCorrespondence>("/claims/" + claimId + "/correspondence/" + itemId + "/submit", { method: "POST" });
}

export function reviewClaimCorrespondence(claimId: string, itemId: string, action: "approve" | "reject", note: string) {
  return apiFetch<import("./types").ClaimCorrespondence>("/claims/" + claimId + "/correspondence/" + itemId + "/" + action, {
    method: "POST", body: JSON.stringify({ note }),
  });
}

export function markClaimCorrespondenceSent(claimId: string, itemId: string, payload: {
  confirm_sent: boolean;
  channel: import("./types").CorrespondenceChannel;
  external_reference?: string | null;
}) {
  return apiFetch<import("./types").ClaimCorrespondence>("/claims/" + claimId + "/correspondence/" + itemId + "/mark-sent", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function listAdjustmentStatements(claimId: string) {
  return apiFetch<import("./types").AdjustmentListResponse>("/claims/" + claimId + "/adjustments");
}

export function createAdjustmentStatement(claimId: string, payload: { currency: string; title?: string | null }) {
  return apiFetch<import("./types").AdjustmentStatement>("/claims/" + claimId + "/adjustments", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function updateAdjustmentStatement(claimId: string, statementId: string, payload: Partial<{
  title: string;
  deductible_amount: string;
  deductible_basis: string;
  other_deduction_amount: string;
  other_deduction_basis: string;
}>) {
  return apiFetch<import("./types").AdjustmentStatement>("/claims/" + claimId + "/adjustments/" + statementId, {
    method: "PATCH", body: JSON.stringify(payload),
  });
}

export function updateAdjustmentLine(claimId: string, statementId: string, lineId: string, payload: {
  treatment: import("./types").AdjustmentTreatment;
  basis: import("./types").AdjustmentBasis;
  considered_amount: string;
  reason?: string | null;
  note?: string | null;
}) {
  return apiFetch<import("./types").AdjustmentStatement>("/claims/" + claimId + "/adjustments/" + statementId + "/lines/" + lineId, {
    method: "PATCH", body: JSON.stringify(payload),
  });
}

export function submitAdjustmentStatement(claimId: string, statementId: string) {
  return apiFetch<import("./types").AdjustmentStatement>("/claims/" + claimId + "/adjustments/" + statementId + "/submit", { method: "POST" });
}

export function reviewAdjustmentStatement(claimId: string, statementId: string, action: "approve" | "reject", note: string) {
  return apiFetch<import("./types").AdjustmentStatement>("/claims/" + claimId + "/adjustments/" + statementId + "/" + action, {
    method: "POST", body: JSON.stringify({ note }),
  });
}

export function getSettlementLedger(claimId: string) {
  return apiFetch<import("./types").SettlementLedger>("/claims/" + claimId + "/settlement-ledger");
}

export function createSettlementProposal(claimId: string, payload: {
  adjustment_statement_id: string; title: string; settlement_type: import("./types").SettlementType;
  amount: string; terms: string; release_required: boolean; without_prejudice: boolean;
}) {
  return apiFetch<import("./types").SettlementProposal>("/claims/" + claimId + "/settlement-ledger/settlements", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function submitSettlementProposal(claimId: string, itemId: string) {
  return apiFetch<import("./types").SettlementProposal>("/claims/" + claimId + "/settlement-ledger/settlements/" + itemId + "/submit", { method: "POST" });
}

export function reviewSettlementProposal(claimId: string, itemId: string, action: "approve" | "reject", note: string) {
  return apiFetch<import("./types").SettlementProposal>("/claims/" + claimId + "/settlement-ledger/settlements/" + itemId + "/" + action, {
    method: "POST", body: JSON.stringify({ note }),
  });
}

export function recordSettlementDisposition(claimId: string, itemId: string, disposition: "accepted" | "declined" | "withdrawn", note: string) {
  return apiFetch<import("./types").SettlementProposal>("/claims/" + claimId + "/settlement-ledger/settlements/" + itemId + "/disposition/record", {
    method: "POST", body: JSON.stringify({ disposition, note }),
  });
}

export function createPaymentAuthorization(claimId: string, payload: { settlement_id: string; payee: string; amount: string; purpose: string }) {
  return apiFetch<import("./types").PaymentAuthorization>("/claims/" + claimId + "/settlement-ledger/payments", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function submitPaymentAuthorization(claimId: string, itemId: string) {
  return apiFetch<import("./types").PaymentAuthorization>("/claims/" + claimId + "/settlement-ledger/payments/" + itemId + "/submit", { method: "POST" });
}

export function reviewPaymentAuthorization(claimId: string, itemId: string, action: "approve" | "reject", note: string) {
  return apiFetch<import("./types").PaymentAuthorization>("/claims/" + claimId + "/settlement-ledger/payments/" + itemId + "/" + action, {
    method: "POST", body: JSON.stringify({ note }),
  });
}

export function recordPaymentPaidExternally(claimId: string, itemId: string, payload: {
  confirm_paid_externally: boolean; channel: string; external_reference: string; value_date: string; note?: string;
}) {
  return apiFetch<import("./types").PaymentAuthorization>("/claims/" + claimId + "/settlement-ledger/payments/" + itemId + "/record-paid", {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function getEmailIngestionInbox() {
  return apiFetch<import("./types").EmailIngestionInbox>("/email-ingestion/inbox");
}
export function createEmailIngestionConnection(payload: {
  provider_label: string; mailbox_address: string; consent_confirmed: boolean;
  consent_basis: string; retention_days: number;
}) {
  return apiFetch<import("./types").EmailIngestionConnection>("/email-ingestion/connections", {
    method: "POST", body: JSON.stringify(payload),
  });
}
export function transitionEmailIngestionConnection(connectionId: string, action: "suspend" | "reactivate" | "revoke", note: string) {
  return apiFetch<import("./types").EmailIngestionConnection>("/email-ingestion/connections/" + connectionId + "/transition", {
    method: "POST", body: JSON.stringify({ action, note }),
  });
}
export function reviewIngestedEmail(messageId: string, payload: {
  action: "link" | "reject"; claim_id?: string; confirm_link?: boolean;
  sensitivity?: "standard" | "confidential" | "privileged_confidential" | "without_prejudice"; note: string;
}) {
  return apiFetch<import("./types").IngestedEmailMessage>("/email-ingestion/messages/" + messageId + "/review", {
    method: "POST", body: JSON.stringify(payload),
  });
}
export function expireDueIngestedEmail() {
  return apiFetch<{ expired_count: number }>("/email-ingestion/expire-due", { method: "POST" });
}

export function getEmailAdapterOperations() {
  return apiFetch<import("./types").EmailAdapterOperations>("/email-ingestion/adapter-operations");
}
export function createEmailProviderAdapter(payload: {
  connection_id: string; provider_kind: "microsoft_graph" | "gmail_api" | "provider_webhook";
  display_name: string; credential_reference: string; allowed_folder: string;
  permission_manifest: string[]; batch_limit: number; retention_schedule_enabled: boolean;
}) {
  return apiFetch<import("./types").EmailProviderAdapter>("/email-ingestion/adapters", { method: "POST", body: JSON.stringify(payload) });
}
export function transitionEmailProviderAdapter(adapterId: string, action: "suspend" | "reactivate" | "revoke", note: string) {
  return apiFetch<import("./types").EmailProviderAdapter>("/email-ingestion/adapters/" + adapterId + "/transition", { method: "POST", body: JSON.stringify({ action, note }) });
}
export function recordEmailAdapterRun(adapterId: string) {
  return apiFetch<import("./types").EmailAdapterRun>("/email-ingestion/adapters/" + adapterId + "/runs", {
    method: "POST", body: JSON.stringify({ idempotency_key: crypto.randomUUID(), trigger: "manual", messages_seen: 0, messages_ingested: 0 }),
  });
}
export function runScheduledEmailRetention() {
  return apiFetch<import("./types").EmailRetentionRun>("/email-ingestion/retention-runs", {
    method: "POST", body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
  });
}
export function getPortalWorkspace(claimId: string) {
  return apiFetch<import("./types").PortalWorkspace>("/claims/" + claimId + "/external-portal");
}
export function createPortalInvitation(claimId: string, payload: {
  participant_name: string; participant_email: string; purpose: string; expires_in_hours: number;
  permission_manifest: string[]; published_items: Array<Record<string, unknown>>;
}) {
  return apiFetch<import("./types").PortalInvitation>("/claims/" + claimId + "/external-portal/invitations", { method: "POST", body: JSON.stringify(payload) });
}
export function revokePortalInvitation(claimId: string, invitationId: string, note: string) {
  return apiFetch<import("./types").PortalInvitation>("/claims/" + claimId + "/external-portal/invitations/" + invitationId + "/revoke", { method: "POST", body: JSON.stringify({ note }) });
}
export function reviewPortalSubmission(claimId: string, submissionId: string, action: "promote" | "reject", note: string) {
  return apiFetch<import("./types").PortalSubmission>("/claims/" + claimId + "/external-portal/submissions/" + submissionId + "/review", {
    method: "POST", body: JSON.stringify({ action, note, confirm_promotion: action === "promote" }),
  });
}
export function proposePortalPublication(claimId: string, invitationId: string, payload: {
  item_type: "correspondence" | "document_metadata"; source_id: string; title: string; summary?: string;
}) {
  return apiFetch<import("./types").PortalPublicationProposal>(`/claims/${claimId}/external-portal/invitations/${invitationId}/publications`, {
    method: "POST", body: JSON.stringify(payload),
  });
}
export function reviewPortalPublication(claimId: string, proposalId: string, action: "approve" | "reject", note: string) {
  return apiFetch<import("./types").PortalPublicationProposal>(`/claims/${claimId}/external-portal/publications/${proposalId}/review`, {
    method: "POST", body: JSON.stringify({ action, note }),
  });
}

export function getPilotOperations() {
  return apiFetch<import("./types").PilotOperationsDashboard>("/pilot-operations");
}
export function createReadinessReview(payload: { environment: "staging" | "pilot"; review_key: string; controls: Record<string, boolean> }) {
  return apiFetch<import("./types").DeploymentReadinessReview>("/pilot-operations/readiness", { method: "POST", body: JSON.stringify(payload) });
}
export function attestReadiness(id: string, note: string) {
  return apiFetch<import("./types").DeploymentReadinessReview>(`/pilot-operations/readiness/${id}/attest`, { method: "POST", body: JSON.stringify({ confirm_ready: true, note }) });
}
export function runOperationalMonitor() {
  return apiFetch<import("./types").OperationalMonitorRun>("/pilot-operations/monitor-runs", { method: "POST", body: JSON.stringify({ idempotency_key: crypto.randomUUID() }) });
}
export function createOperationalIncident(payload: { severity: string; category: string; title: string; summary: string; owner_label: string }) {
  return apiFetch<import("./types").OperationalIncident>("/pilot-operations/incidents", { method: "POST", body: JSON.stringify(payload) });
}
export function transitionOperationalIncident(id: string, action: "acknowledge" | "resolve", note: string) {
  return apiFetch<import("./types").OperationalIncident>(`/pilot-operations/incidents/${id}/transition`, { method: "POST", body: JSON.stringify({ action, note }) });
}
export function writePilotGovernance(payload: { pilot_purpose: string; legal_basis: string; data_owner: string; retention_statement: string; residency_statement: string; exit_contact: string }) {
  return apiFetch<import("./types").PilotGovernanceProfile>("/pilot-operations/governance", { method: "PUT", body: JSON.stringify(payload) });
}
export function approvePilotGovernance(note: string) {
  return apiFetch<import("./types").PilotGovernanceProfile>("/pilot-operations/governance/approve", { method: "POST", body: JSON.stringify({ confirm_approved: true, note }) });
}
export function createPilotExitManifest(claimId: string) {
  return apiFetch<import("./types").PilotExitManifest>(`/pilot-operations/claims/${claimId}/exit-manifests`, { method: "POST", body: JSON.stringify({ idempotency_key: crypto.randomUUID(), confirm_manifest_only: true }) });
}
export function createDesignPartnerRehearsal(readinessReviewId: string) {
  return apiFetch<import("./types").DesignPartnerRehearsal>("/pilot-operations/rehearsals", {
    method: "POST", body: JSON.stringify({ readiness_review_id: readinessReviewId,
      rehearsal_key: `rehearsal-${crypto.randomUUID()}`, name: "Design-partner pilot rehearsal",
      objectives: ["Validate the bounded pilot runbook", "Exercise human escalation paths"],
      participant_roles: ["Claims Manager", "Claims Handler", "Pilot Operations"],
      scheduled_for: new Date(Date.now() + 86400000).toISOString() }),
  });
}
export function startDesignPartnerRehearsal(id: string) {
  return apiFetch<import("./types").DesignPartnerRehearsal>(`/pilot-operations/rehearsals/${id}/start`, { method: "POST" });
}
export function recordRehearsalEvidence(id: string, payload: { control_key: string; evidence_reference: string; evidence_summary: string; result: string }) {
  return apiFetch<import("./types").DesignPartnerRehearsal>(`/pilot-operations/rehearsals/${id}/evidence`, { method: "PUT", body: JSON.stringify(payload) });
}
export function createRehearsalFinding(id: string, payload: { evidence_id?: string; severity: string; title: string; description: string; owner_label: string; due_at: string }) {
  return apiFetch<import("./types").DesignPartnerRehearsal>(`/pilot-operations/rehearsals/${id}/findings`, { method: "POST", body: JSON.stringify(payload) });
}
export function transitionRehearsalFinding(id: string, findingId: string, action: "acknowledge" | "resolve", note: string) {
  return apiFetch<import("./types").DesignPartnerRehearsal>(`/pilot-operations/rehearsals/${id}/findings/${findingId}/transition`, { method: "POST", body: JSON.stringify({ action, note }) });
}
export function completeDesignPartnerRehearsal(id: string, outcome: "go" | "no_go", note: string) {
  return apiFetch<import("./types").DesignPartnerRehearsal>(`/pilot-operations/rehearsals/${id}/complete`, { method: "POST", body: JSON.stringify({ outcome, confirm_decision: true, note }) });
}
export function createPrivatePilotExecution(rehearsalId: string) {
  return apiFetch<import("./types").PrivatePilotExecution>("/pilot-operations/pilot-executions", {
    method: "POST", body: JSON.stringify({ rehearsal_id: rehearsalId,
      execution_key: `private-pilot-${crypto.randomUUID()}`, design_partner_label: "Bounded design partner",
      data_mode: "synthetic", objectives: ["Measure the human-reviewed claims workflow", "Capture accountable product gaps"],
      target_case_runs: 1 }),
  });
}
export function startPrivatePilotExecution(id: string) {
  return apiFetch<import("./types").PrivatePilotExecution>(`/pilot-operations/pilot-executions/${id}/start`, { method: "POST" });
}
export function recordPrivatePilotCaseRun(id: string, payload: {
  claim_id: string; case_outcome: "completed" | "blocked" | "abandoned"; evidence_reference: string;
  triage_minutes?: number; evidence_review_minutes?: number; assessment_minutes?: number; adjustment_minutes?: number;
  ai_candidates_reviewed: number; ai_accepted: number; ai_edited: number; ai_rejected: number;
  rule_findings_reviewed: number; rule_findings_helpful: number; open_conflicts: number; open_requirements: number;
}) {
  return apiFetch<import("./types").PrivatePilotExecution>(`/pilot-operations/pilot-executions/${id}/case-runs`, { method: "PUT", body: JSON.stringify(payload) });
}
export function createProductGap(id: string, payload: {
  case_run_id?: string; priority: "p0" | "p1" | "p2" | "p3"; category: string;
  title: string; summary: string; owner_label: string; due_at: string; evidence_reference?: string;
}) {
  return apiFetch<import("./types").PrivatePilotExecution>(`/pilot-operations/pilot-executions/${id}/gaps`, { method: "POST", body: JSON.stringify(payload) });
}
export function transitionProductGap(id: string, gapId: string, action: "accept" | "resolve" | "wont_fix", note: string) {
  return apiFetch<import("./types").PrivatePilotExecution>(`/pilot-operations/pilot-executions/${id}/gaps/${gapId}/transition`, { method: "POST", body: JSON.stringify({ action, note }) });
}
export function completePrivatePilotExecution(id: string, outcome: "proceed" | "pause" | "stop", note: string) {
  return apiFetch<import("./types").PrivatePilotExecution>(`/pilot-operations/pilot-executions/${id}/complete`, { method: "POST", body: JSON.stringify({ outcome, confirm_outcome: true, note }) });
}
export function createProductionArchitectureBaseline(pilotExecutionId: string) {
  return apiFetch<import("./types").ProductionArchitectureBaseline>("/pilot-operations/architecture-baselines", {
    method: "POST", body: JSON.stringify({ pilot_execution_id: pilotExecutionId,
      baseline_key: `production-baseline-${crypto.randomUUID()}`, deployment_model: "single_tenant_managed",
      data_residency_region: "Approved region — confirm before deployment" }),
  });
}
export function recordProductionArchitectureControl(id: string, payload: {
  control_key: string; current_state: "missing" | "partial" | "implemented" | "not_applicable";
  target_architecture: string; risk_note: string; owner_label: string; target_date: string; evidence_reference?: string;
}) {
  return apiFetch<import("./types").ProductionArchitectureBaseline>(`/pilot-operations/architecture-baselines/${id}/controls`, { method: "PUT", body: JSON.stringify(payload) });
}
export function attestProductionArchitectureBaseline(id: string, note: string) {
  return apiFetch<import("./types").ProductionArchitectureBaseline>(`/pilot-operations/architecture-baselines/${id}/attest`, { method: "POST", body: JSON.stringify({ confirm_reviewed: true, note }) });
}
export function createProductionControlVerificationGate(architectureBaselineId: string) {
  return apiFetch<import("./types").ProductionControlVerificationGate>("/pilot-operations/control-verification-gates", {
    method: "POST", body: JSON.stringify({ architecture_baseline_id: architectureBaselineId,
      gate_key: `architecture-verification-${crypto.randomUUID()}` }),
  });
}
export function submitProductionControlEvidence(id: string, payload: {
  control_key: string; implementation_summary: string; verification_method: string;
  rollback_plan: string; owner_label: string; implementation_completed_at: string;
  evidence_reference: string;
}) {
  return apiFetch<import("./types").ProductionControlVerificationGate>(`/pilot-operations/control-verification-gates/${id}/evidence`, {
    method: "POST", body: JSON.stringify(payload),
  });
}
export function reviewProductionControlEvidence(id: string, evidenceId: string,
  action: "verify" | "reject", note: string, reviewReference?: string) {
  return apiFetch<import("./types").ProductionControlVerificationGate>(`/pilot-operations/control-verification-gates/${id}/evidence/${evidenceId}/review`, {
    method: "POST", body: JSON.stringify({ action, note, review_reference: reviewReference || null }),
  });
}
export function completeProductionControlVerificationGate(id: string, note: string) {
  return apiFetch<import("./types").ProductionControlVerificationGate>(`/pilot-operations/control-verification-gates/${id}/complete`, {
    method: "POST", body: JSON.stringify({ confirm_verified: true, note }),
  });
}
export function createOperationalAcceptance(controlVerificationGateId: string) {
  const checkKeys = ["release_artifact", "migration_plan", "backup_restore",
    "observability_alerting", "incident_response", "rollback_rehearsal", "support_coverage"];
  return apiFetch<import("./types").OperationalAcceptance>("/pilot-operations/operational-acceptances", {
    method: "POST", body: JSON.stringify({
      control_verification_gate_id: controlVerificationGateId,
      acceptance_key: `operational-acceptance-${crypto.randomUUID()}`,
      release_identifier: `release-${crypto.randomUUID()}`,
      target_environment: "production",
      change_window_start: new Date(Date.now() + 86400000).toISOString(),
      change_window_end: new Date(Date.now() + 90000000).toISOString(),
      release_owner_label: "Release Owner", rollback_owner_label: "Rollback Owner",
      incident_commander_label: "Incident Commander", support_owner_label: "Support Owner",
      checks: checkKeys.map((checkKey) => ({ check_key: checkKey, result: "pass",
        owner_label: "Operational Control Owner",
        evidence_reference: `artifact://go-live/${checkKey}`,
        note: `Human-reviewed bounded operational evidence for ${checkKey}.` })),
    }),
  });
}
export function reviewOperationalAcceptance(id: string, approvalRole: "operations" | "risk",
  action: "approve" | "reject") {
  return apiFetch<import("./types").OperationalAcceptance>(`/pilot-operations/operational-acceptances/${id}/approvals`, {
    method: "POST", body: JSON.stringify({ approval_role: approvalRole, action,
      evidence_reference: action === "approve" ? `artifact://go-live/${approvalRole}-review` : null,
      note: action === "approve"
        ? `Independent ${approvalRole} reviewer confirmed every bounded operational check.`
        : `${approvalRole} reviewer rejected this attempt; a fresh attempt is required.` }),
  });
}
export function decideOperationalAcceptance(id: string, outcome: "authorize" | "hold") {
  return apiFetch<import("./types").OperationalAcceptance>(`/pilot-operations/operational-acceptances/${id}/decision`, {
    method: "POST", body: JSON.stringify({ outcome, confirm_decision: true,
      note: outcome === "authorize"
        ? "Administrator recorded a bounded, expiring go-live authorization; deployment and traffic remain separate actions."
        : "Administrator placed this go-live attempt on hold pending a fresh operational acceptance attempt." }),
  });
}

export function getAIGovernance() {
  return apiFetch<import("./types").AIGovernanceDashboard>("/ai-governance");
}

export function createAIProviderActivation(model: string) {
  const expiresAt = new Date(Date.now() + 30 * 86400000).toISOString();
  return apiFetch<import("./types").AIProviderActivation>("/ai-governance/activations", {
    method: "POST",
    body: JSON.stringify({
      request_key: `openai-staging-${crypto.randomUUID()}`,
      environment: "staging",
      provider: "openai",
      provider_project_label: "MCRI bounded staging evaluation",
      model,
      prompt_bundle_version: "2026-08-20.1",
      schema_bundle_version: "2026-08-20.1",
      data_mode: "synthetic_deidentified",
      allowed_document_types: ["chief_engineer_report", "engine_log", "running_hours_record",
        "pms_record", "workshop_report", "quotation", "invoice"],
      restricted_documents_allowed: false,
      credential_storage_mode: "secret_manager",
      max_input_chars: 60000,
      max_output_tokens: 2000,
      requests_per_minute: 10,
      tokens_per_minute: 50000,
      monthly_spend_limit_cents: 10000,
      spend_alert_thresholds: [50, 80],
      retention_mode: "approved_standard",
      data_residency_region: "Approved staging region — verify against DPA",
      security_owner_label: "Security owner",
      privacy_owner_label: "Privacy owner",
      product_owner_label: "Product owner",
      incident_owner_label: "Incident commander",
      kill_switch_owner_label: "AI operations owner",
      credential_control_reference: "artifact://ai-governance/staging-secret-control",
      spend_limit_reference: "monitor://ai-governance/staging-spend-cap",
      data_processing_reference: "artifact://ai-governance/dpa-review",
      kill_switch_reference: "runbook://ai-governance/kill-switch",
      evaluation_expires_at: expiresAt,
    }),
  });
}

export function reviewAIProviderActivation(id: string,
  approvalRole: "security" | "privacy" | "product", action: "approve" | "reject") {
  return apiFetch<import("./types").AIProviderActivation>(`/ai-governance/activations/${id}/approvals`, {
    method: "POST",
    body: JSON.stringify({
      approval_role: approvalRole,
      action,
      evidence_reference: action === "approve"
        ? `artifact://ai-governance/${approvalRole}-review`
        : null,
      note: action === "approve"
        ? `Independent ${approvalRole} reviewer approved the bounded staging evaluation.`
        : `Independent ${approvalRole} reviewer rejected this evaluation attempt.`,
    }),
  });
}

export function decideAIProviderActivation(id: string,
  outcome: "authorize_staging" | "hold") {
  return apiFetch<import("./types").AIProviderActivation>(`/ai-governance/activations/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ outcome, confirm_decision: true,
      note: outcome === "authorize_staging"
        ? "Administrator authorized the bounded, expiring staging evaluation only."
        : "Administrator held this attempt; provider execution remains blocked." }),
  });
}

export function revokeAIProviderActivation(id: string) {
  return apiFetch<import("./types").AIProviderActivation>(`/ai-governance/activations/${id}/revoke`, {
    method: "POST",
    body: JSON.stringify({ confirm_revoke: true,
      note: "Manager activated the application kill switch; future external AI queueing is blocked." }),
  });
}

export function attestAIDocumentEligibility(payload: {
  activation_request_id: string; claim_id: string; document_id: string;
  data_mode: "synthetic" | "deidentified";
}) {
  return apiFetch<import("./types").AIDocumentEligibility>("/ai-governance/document-eligibility", {
    method: "POST",
    body: JSON.stringify({ ...payload, confirm_eligible: true,
      evidence_reference: `artifact://ai-governance/document-${payload.document_id}`,
      note: "Manager attested that this bounded staging document is synthetic or de-identified." }),
  });
}

export function revokeAIDocumentEligibility(id: string) {
  return apiFetch<import("./types").AIDocumentEligibility>(`/ai-governance/document-eligibility/${id}/revoke`, {
    method: "POST",
    body: JSON.stringify({ confirm_revoke: true,
      note: "Manager revoked document eligibility; external AI queueing is blocked for this document." }),
  });
}

export function getAIEvaluation() {
  return apiFetch<import("./types").AIEvaluationDashboard>("/ai-evaluation");
}

export function createAIEvaluationSuite(activationRequestId: string) {
  return apiFetch<import("./types").AIEvaluationSuite>("/ai-evaluation/suites", {
    method: "POST",
    body: JSON.stringify({ activation_request_id: activationRequestId,
      suite_key: `quality-safety-cost-${crypto.randomUUID()}`, confirm_content_free: true }),
  });
}

export function recordAIEvaluationCase(suiteId: string, payload: {
  case_key: string;
  document_type: "chief_engineer_report" | "engine_log";
  scenario_type: "baseline" | "prompt_injection" | "malformed_input" | "cross_tenant" | "restricted_data";
  data_mode: "synthetic" | "deidentified";
  result: "pass" | "fail";
  field_true_positive: number; field_false_positive: number; field_false_negative: number;
  extracted_claim_count: number; unsupported_claim_count: number;
  source_quote_checked_count: number; source_quote_valid_count: number;
  human_approved_count: number; human_edited_count: number; human_rejected_count: number;
  latency_ms: number; input_tokens: number; output_tokens: number;
  observed_provider_cost_microusd: number; boundary_control_passed: boolean;
  evidence_reference: string; note: string;
}) {
  return apiFetch<import("./types").AIEvaluationSuite>(`/ai-evaluation/suites/${suiteId}/cases`, {
    method: "POST",
    body: JSON.stringify({ ...payload, executed_at: new Date().toISOString(),
      confirm_content_free: true }),
  });
}

export function finalizeAIEvaluationSuite(id: string) {
  return apiFetch<import("./types").AIEvaluationSuite>(`/ai-evaluation/suites/${id}/finalize`, {
    method: "POST", body: JSON.stringify({ confirm_finalize: true,
      note: "Manager finalized the immutable content-free benchmark and deterministic thresholds." }),
  });
}

export function reviewAIEvaluationSuite(id: string, reviewRole: "quality" | "risk",
  action: "approve" | "reject") {
  return apiFetch<import("./types").AIEvaluationSuite>(`/ai-evaluation/suites/${id}/reviews`, {
    method: "POST", body: JSON.stringify({ review_role: reviewRole, action,
      evidence_reference: action === "approve" ? `artifact://ai-evaluation/${reviewRole}-review` : null,
      note: action === "approve"
        ? `Independent ${reviewRole} reviewer reproduced the benchmark evidence and thresholds.`
        : `Independent ${reviewRole} reviewer rejected this evaluation attempt.` }),
  });
}

export function decideAIEvaluationPromotion(id: string,
  outcome: "promote_staging" | "hold") {
  return apiFetch<import("./types").AIEvaluationSuite>(`/ai-evaluation/suites/${id}/decision`, {
    method: "POST", body: JSON.stringify({ outcome, confirm_decision: true,
      note: outcome === "promote_staging"
        ? "Administrator promoted only the evaluated synthetic/de-identified staging bundle."
        : "Administrator held this evaluation; shared staging promotion remains blocked." }),
  });
}

export function revokeAIEvaluationPromotion(id: string) {
  return apiFetch<import("./types").AIEvaluationSuite>(`/ai-evaluation/suites/${id}/revoke`, {
    method: "POST", body: JSON.stringify({ confirm_revoke: true,
      note: "Manager revoked the evaluation promotion; shared staging use is blocked." }),
  });
}

export function getAIPrivatePilot() {
  return apiFetch<import("./types").AIPrivatePilotDashboard>("/ai-private-pilot");
}

export function createAIPrivatePilot(evaluationSuiteId: string, anchorExpiresAt?: string | null) {
  const sevenDays = Date.now() + 7 * 86400000;
  const anchorLimit = anchorExpiresAt ? new Date(anchorExpiresAt).getTime() - 60000 : sevenDays;
  const expiresAt = new Date(Math.min(sevenDays, anchorLimit)).toISOString();
  return apiFetch<import("./types").AIPrivatePilot>("/ai-private-pilot/pilots", {
    method: "POST", body: JSON.stringify({
      evaluation_suite_id: evaluationSuiteId,
      pilot_key: `real-document-pilot-${crypto.randomUUID()}`,
      allowed_document_types: ["chief_engineer_report", "engine_log"],
      max_claims: 3, max_documents: 10, max_users: 5, max_provider_runs: 30,
      starts_at: new Date().toISOString(),
      expires_at: expiresAt,
      organization_authorization_reference: "artifact://ai-pilot/organization-authorization",
      data_owner_authorization_reference: "artifact://ai-pilot/data-owner-authorization",
      monitoring_reference: "monitor://ai-pilot/private-cohort",
      incident_runbook_reference: "runbook://ai-pilot/incident-response",
      rollback_reference: "runbook://ai-pilot/immediate-rollback",
      confirm_bounded_real_document_pilot: true,
    }),
  });
}

export function reviewAIPrivatePilot(id: string,
  approvalRole: "organization_owner" | "data_owner", action: "approve" | "reject") {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/pilots/${id}/approvals`, {
    method: "POST", body: JSON.stringify({ approval_role: approvalRole, action,
      evidence_reference: action === "approve" ? `artifact://ai-pilot/${approvalRole}-review` : null,
      note: action === "approve"
        ? `Independent ${approvalRole} approved the exact cohort, document classes and expiry.`
        : `Independent ${approvalRole} rejected this private-pilot attempt.` }),
  });
}

export function decideAIPrivatePilot(id: string, outcome: "authorize_pilot" | "hold") {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/pilots/${id}/decision`, {
    method: "POST", body: JSON.stringify({ outcome, confirm_decision: true,
      note: outcome === "authorize_pilot"
        ? "Administrator authorized only this bounded real non-restricted document cohort."
        : "Administrator held the pilot; real-document provider execution remains blocked." }),
  });
}

export function attestAIPrivatePilotDocument(id: string, payload: {
  claim_id: string; document_id: string;
  authorization_basis: "organization_and_data_owner" | "explicit_data_owner_consent";
  authorization_reference: string; data_minimization_reference: string; note: string;
}) {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/pilots/${id}/documents`, {
    method: "POST", body: JSON.stringify({ ...payload, confirm_real_non_restricted: true }),
  });
}

export function revokeAIPrivatePilotDocument(pilotId: string, eligibilityId: string) {
  return apiFetch<import("./types").AIPrivatePilot>(
    `/ai-private-pilot/pilots/${pilotId}/documents/${eligibilityId}/revoke`, {
      method: "POST", body: JSON.stringify({ confirm_revoke: true,
        note: "Manager revoked document eligibility; further provider runs are blocked." }),
    });
}

export function reviewAIPrivatePilotRun(runId: string,
  humanReviewAction: "approve" | "edit" | "reject") {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/runs/${runId}/outcome`, {
    method: "POST", body: JSON.stringify({ human_review_action: humanReviewAction,
      output_candidate_count: 1, human_edit_count: humanReviewAction === "edit" ? 1 : 0,
      latency_ms: 1, observed_provider_cost_microusd: 0,
      evidence_reference: `artifact://ai-pilot/run-${runId}-human-review`,
      note: "Human reviewer verified candidate output; replace sample metrics with observed evidence.",
      confirm_human_review: true }),
  });
}

export function reportAIPrivatePilotIncident(id: string) {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/pilots/${id}/incidents`, {
    method: "POST", body: JSON.stringify({ severity: "high", category: "quality",
      evidence_reference: `ticket://ai-pilot/${crypto.randomUUID()}`,
      note: "Operator reported a high-severity observation and activated the immediate pilot pause.",
      confirm_pause: true }),
  });
}

export function resolveAIPrivatePilotIncident(pilotId: string, incidentId: string) {
  return apiFetch<import("./types").AIPrivatePilot>(
    `/ai-private-pilot/pilots/${pilotId}/incidents/${incidentId}/resolve`, {
      method: "POST", body: JSON.stringify({
        resolution_reference: `artifact://ai-pilot/incident-${incidentId}-resolution`,
        resolution_note: "Administrator verified remediation and monitoring recovery before resume.",
        resume_pilot: true, confirm_resolution: true }),
    });
}

export function revokeAIPrivatePilot(id: string) {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/pilots/${id}/revoke`, {
    method: "POST", body: JSON.stringify({ confirm_revoke: true,
      note: "Manager activated the immediate private-pilot kill switch." }),
  });
}

export function completeAIPrivatePilot(id: string) {
  return apiFetch<import("./types").AIPrivatePilot>(`/ai-private-pilot/pilots/${id}/complete`, {
    method: "POST", body: JSON.stringify({ confirm_complete: true,
      note: "Every bounded provider run has human review and every incident is resolved." }),
  });
}

export function getAIPilotOutcomes() {
  return apiFetch<import("./types").AIPilotOutcomeDashboard>("/ai-pilot-outcomes");
}

export function createAIPilotOutcomeAssessment(pilotId: string) {
  return apiFetch<import("./types").AIPilotOutcomeAssessment>(
    "/ai-pilot-outcomes/assessments", {
      method: "POST", body: JSON.stringify({ pilot_id: pilotId,
        assessment_key: `private-pilot-exit-${crypto.randomUUID()}`,
        confirm_content_free_assessment: true }),
    });
}

export function recordAIPilotWorkflowObservation(assessmentId: string, payload: {
  pilot_run_id: string; usefulness_rating: number; review_seconds: number;
  workflow_completed: boolean; boundary_control_passed: boolean;
  evidence_reference: string; note: string;
}) {
  return apiFetch<import("./types").AIPilotOutcomeAssessment>(
    `/ai-pilot-outcomes/assessments/${assessmentId}/observations`, {
      method: "POST", body: JSON.stringify({ ...payload,
        confirm_content_free_observation: true }),
    });
}

export function finalizeAIPilotOutcomeAssessment(id: string) {
  return apiFetch<import("./types").AIPilotOutcomeAssessment>(
    `/ai-pilot-outcomes/assessments/${id}/finalize`, {
      method: "POST", body: JSON.stringify({ confirm_finalize: true,
        note: "The completed cohort, per-workflow usability evidence, incidents and observed cost trend were verified before freezing this scorecard." }),
    });
}

export function reviewAIPilotOutcomeAssessment(id: string,
  reviewRole: "product" | "quality" | "risk", action: "approve" | "reject") {
  return apiFetch<import("./types").AIPilotOutcomeAssessment>(
    `/ai-pilot-outcomes/assessments/${id}/reviews`, {
      method: "POST", body: JSON.stringify({ review_role: reviewRole, action,
        evidence_reference: action === "approve"
          ? `artifact://ai-pilot-outcomes/${reviewRole}-review` : null,
        note: action === "approve"
          ? `Independent ${reviewRole} reviewer reproduced the content-free scorecard and exit boundary.`
          : `Independent ${reviewRole} reviewer rejected the private-pilot exit evidence.` }),
    });
}

export function decideAIPilotOutcome(id: string, outcome:
  "recommend_limited_production_evaluation" | "extend_private_pilot" | "stop_ai_progression") {
  return apiFetch<import("./types").AIPilotOutcomeAssessment>(
    `/ai-pilot-outcomes/assessments/${id}/decision`, {
      method: "POST", body: JSON.stringify({ outcome,
        confirm_recommendation_only: true,
        note: outcome === "recommend_limited_production_evaluation"
          ? "Administrator records a recommendation to design a separate limited-production evaluation authorization; this decision grants no production access."
          : outcome === "extend_private_pilot"
            ? "Administrator requires a new bounded private-pilot attempt and additional evidence."
            : "Administrator stops AI progression; no production authorization is granted." }),
  });
}

export function getAILimitedProduction() {
  return apiFetch<import("./types").AILimitedProductionDashboard>("/ai-limited-production");
}

export function createAILimitedProduction(outcomeAssessmentId: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    "/ai-limited-production/authorizations", {
      method: "POST", body: JSON.stringify({
        outcome_assessment_id: outcomeAssessmentId,
        authorization_key: `limited-production-${crypto.randomUUID()}`,
        allowed_document_types: ["chief_engineer_report", "engine_log"],
        rollout_percentage: 10, max_claims: 5, max_documents: 15,
        max_users: 5, max_provider_runs: 50,
        starts_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
        deployment_isolation_reference: "artifact://ai-limited-production/deployment-isolation",
        provider_project_reference: "artifact://ai-limited-production/provider-project",
        credential_control_reference: "artifact://ai-limited-production/credential-control",
        data_processing_reference: "artifact://ai-limited-production/data-processing-approval",
        monitoring_reference: "monitor://ai-limited-production/live-quality-cost",
        rollback_reference: "runbook://ai-limited-production/rollback-15-minutes",
        change_ticket_reference: "ticket://ai-limited-production/change-approval",
        confirm_separate_limited_production_evaluation: true,
      }),
    });
}

export function reviewAILimitedProduction(id: string,
  approvalRole: "security" | "privacy" | "product" | "operations",
  action: "approve" | "reject") {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/approvals`, {
      method: "POST", body: JSON.stringify({ approval_role: approvalRole, action,
        evidence_reference: action === "approve"
          ? `artifact://ai-limited-production/${approvalRole}-review` : null,
        note: action === "approve"
          ? `Independent ${approvalRole} reviewer approved the exact expiring rollout and rollback controls.`
          : `Independent ${approvalRole} reviewer rejected this authorization attempt.` }),
    });
}

export function decideAILimitedProduction(id: string,
  outcome: "authorize_limited_evaluation" | "hold") {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/decision`, {
      method: "POST", body: JSON.stringify({ outcome, confirm_decision: true,
        note: outcome === "authorize_limited_evaluation"
          ? "Administrator authorized only the exact expiring limited-production evaluation; Production-wide use remains blocked."
          : "Administrator held the attempt; all Production AI remains blocked." }),
    });
}

export function attestAILimitedProductionDocument(id: string, payload: {
  claim_id: string; document_id: string; note: string;
}) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/documents`, {
      method: "POST", body: JSON.stringify({ ...payload,
        legal_basis_reference: `artifact://ai-limited-production/document-${payload.document_id}-legal-basis`,
        data_minimization_reference: `artifact://ai-limited-production/document-${payload.document_id}-minimization`,
        change_ticket_reference: `ticket://ai-limited-production/document-${payload.document_id}`,
        confirm_non_restricted_rollout_document: true }),
    });
}

export function reviewAILimitedProductionRun(runId: string,
  action: "approve" | "edit" | "reject") {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/runs/${runId}/outcome`, {
      method: "POST", body: JSON.stringify({ human_review_action: action,
        output_candidate_count: 1, human_edit_count: action === "edit" ? 1 : 0,
        latency_ms: 1, observed_provider_cost_microusd: 0,
        evidence_reference: `artifact://ai-limited-production/run-${runId}-review`,
        note: "Different human verified the candidate output and recorded content-free observed metrics.",
        confirm_human_review: true }),
    });
}

export function monitorAILimitedProduction(id: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/monitors`, {
      method: "POST", body: JSON.stringify({
        monitor_key: `live-monitor-${crypto.randomUUID()}`,
        note: "Operator froze the current human-review, quality, latency, cost and incident snapshot.",
        confirm_live_monitor_snapshot: true }),
    });
}

export function reportAILimitedProductionIncident(id: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/incidents`, {
      method: "POST", body: JSON.stringify({ severity: "high", category: "quality",
        evidence_reference: `ticket://ai-limited-production/incident-${crypto.randomUUID()}`,
        note: "Operator reported a high-severity issue and triggered immediate pause and rollback.",
        confirm_pause_and_rollback: true }),
    });
}

export function resolveAILimitedProductionIncident(id: string, incidentId: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/incidents/${incidentId}/resolve`, {
      method: "POST", body: JSON.stringify({
        resolution_reference: `artifact://ai-limited-production/incident-${incidentId}-resolution`,
        resolution_note: "Administrator verified remediation; a new passing monitor is required before resume.",
        resume_authorization: false, confirm_resolution: true }),
    });
}

export function resumeAILimitedProduction(id: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/resume`, {
      method: "POST", body: JSON.stringify({ confirm_resume: true,
        note: "Administrator verified resolved incidents and a fresh passing monitor before resume." }),
    });
}

export function revokeAILimitedProduction(id: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/revoke`, {
      method: "POST", body: JSON.stringify({ confirm_revoke: true,
        note: "Manager activated the immediate limited-production AI kill switch." }),
    });
}

export function completeAILimitedProduction(id: string) {
  return apiFetch<import("./types").AILimitedProductionAuthorization>(
    `/ai-limited-production/authorizations/${id}/complete`, {
      method: "POST", body: JSON.stringify({ confirm_complete: true,
        note: "Every bounded run is reviewed, incidents are resolved and the latest monitor passes." }),
    });
}
