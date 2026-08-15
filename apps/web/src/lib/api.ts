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
