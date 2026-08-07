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

export interface AIReviewGroup {
  group_key: string;
  group_type: string;
  label: string;
  claim_id: string;
  claim_reference: string;
  vessel_name: string;
  document_id: string;
  document_name: string;
  items: AIReviewItem[];
  pending_count: number;
  needs_attention: boolean;
  attention_reasons: string[];
  group_approvable: boolean;
  requires_reason: boolean;
  min_confidence: string;
}

export interface AIReviewGroupQueueResponse {
  groups: AIReviewGroup[];
  total_groups: number;
  total_extractions: number;
  attention_groups: number;
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
  occurred_on: string | null;
  occurred_time: string | null;
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
  equivalent_claim_fact_id: string | null;
  satisfaction_basis: string | null;
  satisfaction_note: string | null;
  satisfied_by_id: string | null;
  satisfied_at: string | null;
  equivalent_evidence_candidates: Array<{ claim_fact_id: string; field_path: string; value: unknown; source_document_id: string; approved_at: string | null }>;
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

export type CostReviewStatus = "claimed" | "under_review" | "potentially_recoverable" | "potentially_non_recoverable" | "accepted" | "rejected" | "paid";
export interface FinancialCostItem { id:string; document_id:string; document_kind:string; supplier:string|null; document_number:string|null; document_date:string|null; line_index:number; description:string; quantity:string|null; unit:string|null; unit_price:string|null; amount:string; currency:string; category:string|null; review_status:CostReviewStatus; }
export interface FinancialFlag { id:string; flag_type:string; severity:string; title:string; explanation:string; evidence:Record<string,unknown>|null; status:"open"|"explained"|"resolved"|"irrelevant"; resolution_note:string|null; }
export interface QuoteComparisonRow { document_id:string; supplier:string|null; quotation_number:string|null; currency:string|null; total:string|null; scope_summary:string|null; lead_time:string|null; repair_duration:string|null; line_items:Array<Record<string,unknown>>; }
export interface ReserveHistoryRow { id:string; amount:string; currency:string; reason:string; created_by_id:string|null; created_at:string; }
export interface FinancialReviewResponse { claim_id:string; totals_by_currency:Record<string,string>; items:FinancialCostItem[]; flags:FinancialFlag[]; quotations:QuoteComparisonRow[]; reserve_history:ReserveHistoryRow[]; }

export type AssessmentStatus = "draft" | "under_review" | "approved";
export type AssessmentSectionStatus = "pending" | "approved" | "edited";

export interface AssessmentSection {
  id: string;
  section_key: string;
  title: string;
  sort_order: number;
  draft_text: string;
  approved_text: string | null;
  status: AssessmentSectionStatus;
  source_manifest: Array<{ kind: string; id: string; label: string }>;
  reviewed_by_id: string | null;
  reviewed_at: string | null;
}

export interface InitialAssessment {
  id: string;
  claim_id: string;
  version: number;
  status: AssessmentStatus;
  readiness_score: number;
  readiness_state: string;
  blocking_items: string[];
  is_preliminary: boolean;
  generation_override_reason: string | null;
  generated_by_id: string | null;
  approved_by_id: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  sections: AssessmentSection[];
}

export interface PilotSession {
  id: string;
  claim_id: string;
  participant_user_id: string | null;
  participant_role: string;
  objective: string | null;
  baseline_assessment_minutes: number | null;
  status: "active" | "completed" | "abandoned";
  started_at: string;
  ended_at: string | null;
  created_at: string;
}

export interface PilotMetrics {
  session_id: string;
  session_status: string;
  elapsed_seconds: number;
  baseline_assessment_minutes: number | null;
  time_to_first_assessment_minutes: number | null;
  estimated_time_reduction_percent: number | null;
  ai_review_total: number;
  ai_approved: number;
  ai_edited: number;
  ai_rejected: number;
  ai_acceptance_rate: number | null;
  ai_edit_rate: number | null;
  ai_reject_rate: number | null;
  feedback_count: number;
  average_rating: number | null;
  false_positive_count: number;
  false_negative_count: number;
  validated_correct_count: number;
  missing_document_precision: number | null;
  missing_document_recall_proxy: number | null;
  friction_count: number;
  tasks_completed: number;
  average_task_completion_minutes: number | null;
  document_requests_sent: number;
}

export interface PilotBacklogItem {
  feedback_id: string;
  priority: "P0" | "P1" | "P2" | "P3";
  category: string;
  title: string;
  rationale: string;
  entity_type: string | null;
  entity_id: string | null;
}

export interface PilotScorecard {
  metrics: PilotMetrics;
  targets: Record<string, number>;
  checks: Record<string, boolean | null>;
  ready_for_next_pilot: boolean;
  backlog: PilotBacklogItem[];
}

export interface PilotCommercialValidation {
  id: string;
  session_id: string;
  claim_id: string;
  recorded_by_id: string | null;
  annual_claim_volume: number | null;
  expected_users: number | null;
  fully_loaded_hourly_cost: string | number | null;
  adoption_rate: string | number | null;
  currency: string;
  buyer_role: string | null;
  champion_role: string | null;
  budget_owner_role: string | null;
  procurement_owner_role: string | null;
  security_approver_role: string | null;
  budget_status: "unknown" | "no_budget" | "exploring" | "budget_identified" | "approved";
  buying_stage: "problem_validation" | "solution_evaluation" | "pilot" | "business_case" | "procurement" | "contracting" | "no_interest";
  decision_timeline_days: number | null;
  pilot_fee_willingness: string | number | null;
  annual_wtp_min: string | number | null;
  annual_wtp_max: string | number | null;
  preferred_pricing_model: "unknown" | "pilot_fee" | "annual_platform" | "per_user" | "per_claim" | "usage";
  deployment_preference: "unknown" | "cloud" | "private_cloud" | "on_prem";
  value_hypotheses: string[];
  must_have_features: string[];
  required_integrations: string[];
  security_requirements: string[];
  blockers: string[];
  respondent_outcome: "unknown" | "interested" | "pilot_extension" | "business_case" | "procurement" | "no_interest";
  next_step: string | null;
  next_step_due_date: string | null;
  commercial_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PilotROIEstimate {
  currency: string;
  minutes_saved_per_claim: number | null;
  annual_claim_volume: number | null;
  adoption_rate: number | null;
  annual_claims_in_scope: number | null;
  annual_hours_saved: number | null;
  annual_labor_value: number | null;
  annual_wtp_midpoint: number | null;
  estimated_roi_multiple: number | null;
  estimated_payback_months: number | null;
  assumptions_complete: boolean;
  note: string;
}

export interface PilotCommercialScorecard {
  session_id: string;
  commercial_validation: PilotCommercialValidation | null;
  roi: PilotROIEstimate;
  checks: Record<string, boolean | null>;
  recommended_validation_decision: "GO" | "PIVOT" | "STOP" | "INSUFFICIENT_DATA";
  rationale: string[];
  next_step: string | null;
}
