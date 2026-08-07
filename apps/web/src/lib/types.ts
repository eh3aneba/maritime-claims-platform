export type UserRole = "admin" | "claims_manager" | "claims_handler";

export interface CurrentUser {
  id: string;
  organization_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
}

export type ClaimStatus =
  | "new"
  | "triage"
  | "awaiting_documents"
  | "investigation"
  | "technical_review"
  | "financial_review"
  | "coverage_review"
  | "negotiation"
  | "settlement"
  | "recovery"
  | "closed"
  | "on_hold"
  | "litigation"
  | "rejected"
  | "withdrawn";

export type ClaimPriority = "low" | "medium" | "high" | "critical";

export interface VesselBrief {
  id: string;
  name: string;
  imo_number: string | null;
}

export interface Vessel extends VesselBrief {
  organization_id: string;
  vessel_type: string | null;
  flag: string | null;
  class_society: string | null;
  year_built: number | null;
  deadweight: string | null;
  owner: string | null;
  manager: string | null;
}

export interface ClaimHandler {
  id: string;
  full_name: string;
  email: string;
  role: UserRole;
}

export interface Claim {
  id: string;
  organization_id: string;
  claim_reference: string;
  external_reference: string | null;
  claim_type: "hull_machinery";
  claim_subtype: "machinery_damage";
  status: ClaimStatus;
  priority: ClaimPriority;
  incident_date: string;
  notification_date: string;
  incident_description: string;
  estimated_loss: string | null;
  current_reserve: string | null;
  currency: string;
  vessel: VesselBrief;
  handler: ClaimHandler | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimListResponse {
  items: Claim[];
  total: number;
  limit: number;
  offset: number;
}

export interface VesselListResponse {
  items: Vessel[];
  total: number;
}

export type DocumentProcessingStatus = "uploaded" | "processing" | "processed" | "failed";
export type ConfidentialityLevel = "internal" | "confidential" | "restricted";

export interface ClaimDocument {
  id: string;
  claim_id: string;
  filename: string;
  original_filename: string;
  document_type: string | null;
  mime_type: string;
  file_size_bytes: number;
  file_hash: string;
  version_number: number;
  processing_status: DocumentProcessingStatus;
  confidentiality_level: ConfidentialityLevel;
  uploaded_by_id: string | null;
  created_at: string;
}

export interface DocumentListResponse {
  items: ClaimDocument[];
  total: number;
}


export type AISemanticKind = "fact" | "opinion" | "inference";
export type AIReviewStatus = "pending" | "approved" | "edited" | "rejected";

export interface AIReviewItem {
  extraction_id: string;
  claim_id: string;
  claim_reference: string;
  vessel_name: string;
  document_id: string;
  document_name: string;
  field_path: string;
  semantic_kind: AISemanticKind;
  ai_value: unknown;
  normalized_value: unknown;
  confidence: string;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_quote: string | null;
  source_verified: boolean;
  validation_warnings: string[] | null;
  human_status: AIReviewStatus;
  approved_value: unknown;
  reviewed_at: string | null;
  bulk_approvable: boolean;
  created_at: string;
}

export interface AIReviewQueueResponse {
  items: AIReviewItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ClaimFact {
  id: string;
  claim_id: string;
  field_path: string;
  value: unknown;
  source_extraction_id: string;
  source_document_id: string;
  source_segment_id: string | null;
  approved_by_id: string | null;
  approved_at: string;
  version: number;
}

export interface AIReviewResult {
  extraction_id: string;
  human_status: AIReviewStatus;
  approved_value: unknown;
  promoted: boolean;
  claim_fact: ClaimFact | null;
}

export interface AISourcePreview {
  extraction_id: string;
  claim_id: string;
  document_id: string;
  document_name: string;
  field_path: string;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_quote: string | null;
  source_verified: boolean;
  segment_id: string | null;
  segment_text: string | null;
}

export interface ClaimFactListResponse {
  items: ClaimFact[];
  total: number;
}


export interface AIFeedbackEntry {
  id: string;
  action: "approved" | "edited" | "rejected";
  ai_value: unknown;
  human_value: unknown;
  reason: string | null;
  reviewer_id: string | null;
  reviewer_name: string | null;
  reviewer_email: string | null;
  created_at: string;
}

export interface AIReviewDetail {
  item: AIReviewItem;
  feedback: AIFeedbackEntry[];
  current_claim_fact: ClaimFact | null;
}


export interface EngineLogEventCandidate {
  event_index: number;
  values: Record<string, unknown>;
  review_statuses: Record<string, AIReviewStatus>;
  source_verified: boolean;
  source_locators: Array<{ type: string | null; value: string | null; quote: string | null }>;
  human_review_complete: boolean;
  timestamp_candidate: { date?: unknown; time?: unknown; timezone?: unknown };
}

export interface EngineLogEventsResponse {
  run: {
    id: string;
    task: string;
    status: "pending" | "running" | "completed" | "failed";
    document_type_candidate: string | null;
    classification_confidence: string | null;
    warnings: string[] | null;
  } | null;
  events: EngineLogEventCandidate[];
}

export type ChronologyMateriality = "low" | "medium" | "high" | "critical";
export type EvidenceConflictStatus = "open" | "explained" | "resolved" | "accepted_difference" | "irrelevant";

export interface ChronologyEvidence {
  extraction_id: string;
  document_id: string;
  document_name: string;
  document_type: string | null;
  field_path: string;
  value: unknown;
  source_quote: string | null;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_verified: boolean;
  evidence_role: string;
}

export interface ChronologyEvent {
  id: string;
  event_type: string;
  title: string;
  description: string | null;
  occurred_on: string;
  occurred_time: string;
  timezone_label: string | null;
  materiality: ChronologyMateriality;
  evidence: ChronologyEvidence[];
  created_at: string;
  updated_at: string;
}

export interface EvidenceConflict {
  id: string;
  conflict_type: string;
  topic: string;
  description: string;
  value_a: unknown;
  value_b: unknown;
  difference_minutes: string | null;
  materiality: ChronologyMateriality;
  status: EvidenceConflictStatus;
  resolution_note: string | null;
  event_a_id: string | null;
  event_b_id: string | null;
  evidence_a_extraction_id: string | null;
  evidence_b_extraction_id: string | null;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimChronologyResponse {
  events: ChronologyEvent[];
  conflicts: EvidenceConflict[];
  event_count: number;
  open_conflict_count: number;
}

export type RequirementPriority = "critical" | "important" | "supporting";
export type RequirementStatus = "missing" | "requested" | "received" | "under_review" | "accepted" | "rejected" | "superseded" | "not_required";
export type ClaimIssueCategory = "technical" | "insurance" | "financial" | "evidence" | "operational" | "workflow";
export type ClaimIssueSeverity = "low" | "medium" | "high" | "critical";
export type ClaimIssueStatus = "open" | "under_review" | "resolved" | "dismissed";

export interface ClaimDocumentRequirement {
  id: string;
  rule_id: string;
  rule_version: string;
  document_type: string;
  document_label: string;
  priority: RequirementPriority;
  required_from_status: string;
  reason: string;
  status: RequirementStatus;
  matched_document_id: string | null;
  is_active: boolean;
  last_evaluated_at: string | null;
}

export interface RuleGeneratedIssue {
  id: string;
  issue_key: string;
  rule_id: string;
  rule_version: string;
  category: ClaimIssueCategory;
  title: string;
  description: string;
  severity: ClaimIssueSeverity;
  status: ClaimIssueStatus;
  evidence: Record<string, unknown> | null;
  explanation: string | null;
  is_active: boolean;
  last_triggered_at: string | null;
}

export interface ClaimReadiness {
  score: number;
  state: "ready" | "limited" | "not_ready" | string;
  critical_missing_count: number;
  important_missing_count: number;
  blocking_items: string[];
  satisfied_weight: number;
  total_weight: number;
}

export interface ClaimRuleSummary {
  ruleset_name: string;
  ruleset_version: string;
  claim_id: string;
  evaluated_at: string | null;
  requirements: ClaimDocumentRequirement[];
  issues: RuleGeneratedIssue[];
  readiness: ClaimReadiness;
  triggered_rule_ids: string[];
}

export type ClaimTaskStatus = "open" | "completed" | "cancelled";
export type ClaimTaskPriority = "low" | "medium" | "high" | "critical";
export type ClaimTaskSource = "human" | "rule" | "ai_suggestion";
export type ClaimTaskType = "document_request" | "review" | "follow_up";

export interface ClaimTask {
  id: string;
  claim_id: string;
  requirement_id: string | null;
  request_batch_id: string | null;
  assignee_id: string | null;
  title: string;
  description: string | null;
  task_type: ClaimTaskType;
  status: ClaimTaskStatus;
  priority: ClaimTaskPriority;
  source: ClaimTaskSource;
  due_date: string | null;
  completed_at: string | null;
  completion_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimTaskListResponse { items: ClaimTask[]; total: number; }

export interface DocumentRequestBatch {
  id: string;
  claim_id: string;
  recipient_label: string | null;
  subject: string;
  draft_body: string;
  requirement_ids: string[];
  status: "draft" | "sent_externally" | "cancelled";
  due_date: string | null;
  created_at: string;
}

export interface DocumentRequestResult {
  batch: DocumentRequestBatch;
  tasks: ClaimTask[];
}

export interface TechnicalEvidenceItem {
  extraction_id: string | null;
  field_path: string;
  value: unknown;
  document_id: string | null;
  source_quote: string | null;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_verified: boolean | null;
}

export interface TechnicalMatrixRow {
  key: string;
  title: string;
  severity: string;
  status: string;
  evidence_for: unknown[];
  evidence_against: unknown[];
  unknown_or_missing: string[];
  recommended_follow_up: string[];
  explanation: string;
}

export interface TechnicalReviewResponse {
  maintenance_facts: Record<string, unknown>;
  workshop_findings: TechnicalEvidenceItem[];
  workshop_repair_options: TechnicalEvidenceItem[];
  workshop_cause_opinions: TechnicalEvidenceItem[];
  matrix: TechnicalMatrixRow[];
  generated_at: string;
}
