export type UserRole = "admin" | "claims_manager" | "claims_handler";

export type EmailConnectionStatus = "active" | "suspended" | "revoked";
export type IngestedEmailStatus = "pending_review" | "linked" | "rejected" | "expired";
export interface EmailIngestionConnection {
  id: string; provider_label: string; mailbox_address: string; status: EmailConnectionStatus;
  consent_basis: string; consent_confirmed_at: string; retention_days: number;
  last_ingested_at: string | null; revoked_at: string | null; created_at: string; ingestion_token?: string | null;
}
export interface EmailAttachmentManifest {
  id: string; filename: string; mime_type: string; file_size_bytes: number;
  provider_sha256: string | null; admission_status: string;
}
export interface IngestedEmailMessage {
  id: string; connection_id: string; suggested_claim_id: string | null; linked_claim_id: string | null;
  correspondence_id: string | null; provider_message_id: string; internet_message_id: string | null;
  sender: string; recipients: string[]; cc: string[]; subject: string; body_text: string;
  status: IngestedEmailStatus; content_hash: string; review_note: string | null;
  received_at: string; retain_until: string; reviewed_at: string | null; created_at: string;
  attachments: EmailAttachmentManifest[];
}
export interface EmailIngestionInbox { connections: EmailIngestionConnection[]; messages: IngestedEmailMessage[]; }
export interface EmailProviderAdapter {
  id: string; connection_id: string; provider_kind: string; display_name: string;
  credential_reference: string; allowed_folder: string; permission_manifest: string[];
  status: string; batch_limit: number; retention_schedule_enabled: boolean;
  next_sync_at: string | null; last_sync_at: string | null; checkpoint_hash: string | null;
  revoked_at: string | null; created_at: string;
}
export interface EmailAdapterRun {
  id: string; adapter_id: string; idempotency_key: string; trigger: string; status: string;
  messages_seen: number; messages_ingested: number; checkpoint_hash: string | null;
  failure_summary: string | null; started_at: string; finished_at: string | null;
}
export interface EmailRetentionRun { id: string; idempotency_key: string; expired_count: number; started_at: string; finished_at: string; }
export interface EmailAdapterOperations { adapters: EmailProviderAdapter[]; runs: EmailAdapterRun[]; retention_runs: EmailRetentionRun[]; }
export interface PortalPublishedItem { id: string; item_type: string; source_id: string; title: string; summary: string | null; created_at: string; }
export interface PortalInvitation {
  id: string; claim_id: string; participant_name: string; participant_email: string; purpose: string;
  permission_manifest: string[]; status: string; expires_at: string; accepted_at: string | null;
  revoked_at: string | null; created_at: string; invitation_token?: string | null; published_items: PortalPublishedItem[];
}
export interface PortalSubmission {
  id: string; claim_id: string; invitation_id: string; correspondence_id: string | null;
  subject: string; body: string; attachment_manifests: Array<Record<string, unknown>>;
  status: string; review_note: string | null; submitted_at: string; reviewed_at: string | null; created_at: string;
}
export interface PortalPublicationProposal {
  id: string; invitation_id: string; published_item_id: string | null; item_type: string; source_id: string;
  title: string; summary: string | null; status: string; review_note: string | null;
  reviewed_at: string | null; created_at: string;
}
export interface PortalWorkspace {
  invitations: PortalInvitation[]; submissions: PortalSubmission[]; publication_proposals: PortalPublicationProposal[];
}

export interface DeploymentReadinessReview {
  id: string; environment: string; review_key: string; controls: Record<string, boolean>; status: string;
  snapshot_hash: string; attestation_note: string | null; attested_at: string | null; created_at: string;
}
export interface OperationalMonitorRun {
  id: string; idempotency_key: string; metrics: Record<string, number>; alerts: Array<Record<string, unknown>>;
  status: string; run_at: string; created_at: string;
}
export interface OperationalIncident {
  id: string; monitor_run_id: string | null; severity: string; category: string; title: string; summary: string;
  owner_label: string; status: string; acknowledged_at: string | null; resolved_at: string | null;
  resolution_note: string | null; created_at: string;
}
export interface PilotGovernanceProfile {
  id: string; pilot_purpose: string; legal_basis: string; data_owner: string; retention_statement: string;
  residency_statement: string; exit_contact: string; status: string; approved_at: string | null;
  created_at: string; updated_at: string;
}
export interface PilotExitManifest {
  id: string; claim_id: string; governance_profile_id: string; idempotency_key: string;
  confirm_manifest_only: boolean; manifest: Record<string, unknown>; manifest_checksum: string;
  status: string; authorized_at: string; created_at: string;
}
export interface RehearsalControlEvidence {
  id: string; rehearsal_id: string; control_key: string; evidence_reference: string;
  evidence_summary: string; result: string; recorded_at: string; created_at: string;
}
export interface RehearsalRemediationFinding {
  id: string; rehearsal_id: string; evidence_id: string | null; severity: string; title: string;
  description: string; owner_label: string; due_at: string; status: string;
  acknowledged_at: string | null; resolved_at: string | null; resolution_note: string | null; created_at: string;
}
export interface DesignPartnerRehearsal {
  id: string; readiness_review_id: string; rehearsal_key: string; name: string; objectives: string[];
  participant_roles: string[]; status: string; scheduled_for: string; started_at: string | null;
  completed_at: string | null; outcome: string | null; decision_note: string | null;
  decision_hash: string | null; evidence: RehearsalControlEvidence[];
  findings: RehearsalRemediationFinding[]; created_at: string;
}
export interface PrivatePilotCaseRun {
  id: string; execution_id: string; claim_id: string; case_outcome: string;
  evidence_reference: string; triage_minutes: number | null; evidence_review_minutes: number | null;
  assessment_minutes: number | null; adjustment_minutes: number | null;
  ai_candidates_reviewed: number; ai_accepted: number; ai_edited: number; ai_rejected: number;
  rule_findings_reviewed: number; rule_findings_helpful: number;
  open_conflicts: number; open_requirements: number; recorded_at: string; created_at: string;
}
export interface ProductGapFinding {
  id: string; execution_id: string; case_run_id: string | null; priority: string; category: string;
  title: string; summary: string; owner_label: string; due_at: string;
  evidence_reference: string | null; status: string; resolution_note: string | null;
  resolved_at: string | null; created_at: string;
}
export interface PrivatePilotExecution {
  id: string; rehearsal_id: string; execution_key: string; design_partner_label: string;
  data_mode: string; data_authorization_reference: string | null; objectives: string[];
  target_case_runs: number; status: string; started_at: string | null; completed_at: string | null;
  outcome: string | null; outcome_note: string | null; outcome_hash: string | null;
  aggregate_metrics: Record<string, unknown>; case_runs: PrivatePilotCaseRun[];
  product_gaps: ProductGapFinding[]; created_at: string;
}
export interface ProductionArchitectureControl {
  id: string; baseline_id: string; control_key: string;
  current_state: "missing" | "partial" | "implemented" | "not_applicable";
  target_architecture: string; risk_note: string; owner_label: string;
  target_date: string; evidence_reference: string | null; created_at: string; updated_at: string;
}
export interface ProductionArchitectureBaseline {
  id: string; pilot_execution_id: string; baseline_key: string; deployment_model: string;
  data_residency_region: string; status: string; snapshot_hash: string | null;
  attestation_note: string | null; attested_at: string | null; summary: Record<string, unknown>;
  controls: ProductionArchitectureControl[]; created_at: string;
}
export interface ProductionControlEvidence {
  id: string; gate_id: string; submitted_by_id: string | null; reviewed_by_id: string | null;
  control_key: string; submission_version: number; implementation_summary: string;
  verification_method: string; rollback_plan: string; owner_label: string;
  implementation_completed_at: string; evidence_reference: string;
  status: "submitted" | "verified" | "rejected"; review_reference: string | null;
  review_note: string | null; submitted_at: string; reviewed_at: string | null; created_at: string;
}
export interface ProductionControlVerificationSummary {
  verification_profile: string; required_control_count: number; required_controls: string[];
  current_submission_count: number;
  total_submission_count: number; status_counts: Record<string, number>;
  all_independently_verified: boolean; production_certification: false;
  go_live_authorization: false; content_or_secrets_included: false;
}
export interface ProductionControlVerificationGate {
  id: string; architecture_baseline_id: string; gate_key: string; verification_profile: string;
  status: string;
  outcome_note: string | null; outcome_hash: string | null; completed_at: string | null;
  summary: ProductionControlVerificationSummary; evidence: ProductionControlEvidence[]; created_at: string;
}
export interface OperationalAcceptanceCheck {
  id: string; acceptance_id: string; check_key: string; result: "pass" | "fail";
  owner_label: string; evidence_reference: string; note: string; created_at: string;
}
export interface OperationalAcceptanceApproval {
  id: string; acceptance_id: string; approver_id: string | null;
  approval_role: "operations" | "risk"; action: "approve" | "reject";
  evidence_reference: string | null; note: string; approved_at: string; created_at: string;
}
export interface OperationalAcceptanceSummary {
  required_check_count: number; recorded_check_count: number; pass_count: number; fail_count: number;
  independent_approvals_complete: boolean; go_live_authorization_recorded: boolean;
  authorization_active: boolean; deployment_performed: false; traffic_enabled: false;
  production_certification: false; external_ai_authorization: false;
  content_or_secrets_included: false;
}
export interface OperationalAcceptance {
  id: string; control_verification_gate_id: string; requested_by_id: string | null;
  finalized_by_id: string | null; attempt_number: number; acceptance_key: string;
  release_identifier: string; target_environment: "production";
  change_window_start: string; change_window_end: string;
  release_owner_label: string; rollback_owner_label: string;
  incident_commander_label: string; support_owner_label: string;
  status: string; outcome: string | null; decision_note: string | null;
  decision_hash: string | null; decided_at: string | null;
  authorization_expires_at: string | null; summary: OperationalAcceptanceSummary;
  checks: OperationalAcceptanceCheck[]; approvals: OperationalAcceptanceApproval[];
  created_at: string;
}
export interface PilotOperationsDashboard {
  readiness_reviews: DeploymentReadinessReview[]; monitor_runs: OperationalMonitorRun[];
  incidents: OperationalIncident[]; governance_profile: PilotGovernanceProfile | null;
  exit_manifests: PilotExitManifest[]; rehearsals: DesignPartnerRehearsal[];
  pilot_executions: PrivatePilotExecution[];
  architecture_baselines: ProductionArchitectureBaseline[];
  control_verification_gates: ProductionControlVerificationGate[];
  operational_acceptances: OperationalAcceptance[];
}

export type SettlementStatus = "draft" | "under_review" | "approved" | "rejected" | "accepted" | "declined" | "withdrawn";
export type SettlementType = "interim" | "partial" | "final";
export type PaymentStatus = "draft" | "under_review" | "first_approved" | "authorized" | "rejected" | "paid_externally" | "cancelled";

export interface SettlementProposal {
  id: string; claim_id: string; adjustment_statement_id: string;
  created_by_id: string | null; reviewed_by_id: string | null; disposition_by_id: string | null;
  version: number; title: string; settlement_type: SettlementType; status: SettlementStatus;
  currency: string; amount: string; terms: string; release_required: boolean; without_prejudice: boolean;
  expires_on: string | null; source_adjustment_hash: string; source_snapshot: Record<string, unknown>;
  review_note: string | null; disposition_note: string | null; content_hash: string | null;
  reviewed_at: string | null; disposition_at: string | null; created_at: string; updated_at: string;
}

export interface PaymentAuthorization {
  id: string; claim_id: string; settlement_id: string; created_by_id: string | null;
  first_approved_by_id: string | null; second_approved_by_id: string | null; paid_recorded_by_id: string | null;
  sequence: number; status: PaymentStatus; payee: string; currency: string; amount: string; purpose: string;
  first_approval_note: string | null; second_approval_note: string | null; rejection_note: string | null;
  content_hash: string | null; first_approved_at: string | null; second_approved_at: string | null;
  paid_channel: string | null; external_reference: string | null; value_date: string | null;
  paid_note: string | null; paid_recorded_at: string | null; created_at: string; updated_at: string;
}

export interface SettlementLedger {
  settlements: SettlementProposal[];
  payments: PaymentAuthorization[];
}

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

export type ClaimIntakeStatus =
  | "processing"
  | "pending_review"
  | "approved"
  | "rejected"
  | "failed"
  | "infected"
  | "scan_error";

export interface ClaimIntakeFields {
  vessel_name?: string | null;
  imo_number?: string | null;
  incident_date?: string | null;
  notification_date?: string | null;
  incident_description?: string | null;
  external_reference?: string | null;
  claim_type?: "hull_machinery";
  claim_subtype?: "machinery_damage";
  priority?: ClaimPriority;
  currency?: string;
}

export interface ClaimIntakeDraft {
  id: string;
  organization_id: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  file_hash: string;
  malware_scan_status: DocumentMalwareScanStatus;
  status: ClaimIntakeStatus;
  extraction_method: string | null;
  ocr_languages: string | null;
  extraction_warnings: string[] | null;
  classification_candidate: string | null;
  classification_confidence: number | null;
  classification_rule: string | null;
  extracted_fields: ClaimIntakeFields | null;
  field_evidence: Record<string, { quote?: string | null; confidence?: number; note?: string }> | null;
  approved_claim_id: string | null;
  source_document_id: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  uploaded_by_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimIntakeApprovalResult {
  draft: ClaimIntakeDraft;
  claim: Claim;
}

export type DocumentProcessingStatus = "uploaded" | "processing" | "processed" | "failed";
export type ConfidentialityLevel = "internal" | "confidential" | "restricted";
export type DocumentMalwareScanStatus =
  | "legacy_unscanned"
  | "clean"
  | "infected_quarantined"
  | "scan_error";
export type QuarantineStatus = "infected" | "scan_error" | "released" | "purged";

export interface ClaimDocument {
  id: string;
  claim_id: string;
  filename: string;
  original_filename: string;
  document_type: string | null;
  mime_type: string;
  file_size_bytes: number;
  file_hash: string;
  document_family_id: string;
  supersedes_document_id: string | null;
  version_number: number;
  is_current: boolean;
  replacement_reason: string | null;
  superseded_at: string | null;
  superseded_by_id: string | null;
  processing_status: DocumentProcessingStatus;
  confidentiality_level: ConfidentialityLevel;
  malware_scan_status: DocumentMalwareScanStatus;
  malware_scanned_at: string | null;
  uploaded_by_id: string | null;
  created_at: string;
}

export interface QuarantinedUpload {
  id: string;
  claim_id: string;
  source_document_id: string | null;
  replaces_document_id: string | null;
  replacement_reason: string | null;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  file_hash: string;
  status: QuarantineStatus;
  threat_name: string | null;
  scanned_at: string;
  retry_count: number;
  last_retried_at: string | null;
  uploaded_by_id: string | null;
  created_at: string;
}

export interface DocumentListResponse {
  items: ClaimDocument[];
  total: number;
  quarantined_items: QuarantinedUpload[];
  quarantined_total: number;
}

export interface LegacyRescanResponse {
  queued_count: number;
  skipped_count: number;
  jobs: Array<{ job_id: string; document_id: string; status: string }>;
}

export interface QuarantineRetryResponse {
  quarantine_id: string;
  status: QuarantineStatus;
  retry_count: number;
  released_document_id: string | null;
  threat_name: string | null;
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

export interface DesignPartnerAccount {
  id: string;
  name: string;
  account_type: "marine_insurer" | "ship_manager" | "p_and_i_correspondent" | "average_adjuster" | "broker" | "other";
  country: string | null;
  region: string | null;
  stage: "prospect" | "contacted" | "discovery" | "demo" | "pilot_qualified" | "pilot_proposed" | "pilot_active" | "paid_pilot" | "customer" | "no_fit";
  qualification_score: number;
  qualification_rationale: string | null;
  next_step: string | null;
  next_step_due_date: string | null;
  machinery_claim_volume_score: number;
  pain_intensity_score: number;
  buyer_access_score: number;
  data_availability_score: number;
  security_fit_score: number;
  pilot_willingness_score: number;
  created_at: string;
}
export interface CohortAccount extends DesignPartnerAccount { qualification_band: "A" | "B" | "C" | "D"; recommended_action: string; }
export interface DesignPartnerCohortSummary {
  target_qualified_partners: number; target_paid_pilots: number; accounts_total: number; a_tier: number; b_tier: number; pilot_qualified: number; paid_pilots: number;
  target_progress: { qualified: number; paid: number }; accounts: CohortAccount[];
}


export type EvidenceMatrixRowStatus =
  | "supported"
  | "conflict_open"
  | "conflict_reviewed"
  | "source_superseded"
  | "source_deleted"
  | "unsupported"
  | "conflict_only";

export interface EvidenceMatrixSource {
  extraction_id: string;
  document_id: string;
  document_family_id: string;
  document_name: string;
  document_type: string | null;
  document_version: number;
  document_is_current: boolean;
  document_deleted: boolean;
  authoritative: boolean;
  semantic_kind: string;
  human_status: string;
  source_verified: boolean;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_quote: string | null;
}

export interface EvidenceMatrixConflict {
  id: string;
  topic: string;
  conflict_type: string;
  description: string;
  value_a: unknown;
  value_b: unknown;
  difference_minutes: string | null;
  materiality: string;
  status: string;
  resolution_note: string | null;
  evidence_a_extraction_id: string | null;
  evidence_b_extraction_id: string | null;
}

export interface EvidenceMatrixRow {
  row_key: string;
  topic: string;
  field_path: string | null;
  fact_id: string | null;
  fact_value: unknown;
  fact_version: number | null;
  approved_at: string | null;
  supporting_evidence: EvidenceMatrixSource[];
  conflicting_evidence: EvidenceMatrixConflict[];
  status: EvidenceMatrixRowStatus;
}

export interface EvidenceMatrixResponse {
  claim_id: string;
  generated_at: string;
  rows: EvidenceMatrixRow[];
  summary: {
    approved_fact_count: number;
    matrix_row_count: number;
    supporting_source_count: number;
    current_source_document_count: number;
    historical_source_document_count: number;
    open_conflict_count: number;
    reviewed_conflict_count: number;
    superseded_fact_source_count: number;
  };
}


export type ClaimPackFormat = "pdf" | "xlsx";

export interface ClaimPackExport {
  id: string;
  claim_id: string;
  export_format: ClaimPackFormat;
  snapshot_schema_version: string;
  snapshot_hash: string;
  filename: string;
  mime_type: string;
  file_hash: string;
  file_size_bytes: number;
  generation_note: string | null;
  generated_by_id: string | null;
  created_at: string;
}

export interface ClaimPackExportListResponse {
  items: ClaimPackExport[];
  total: number;
}


export interface PolicyTermSource {
  document_id: string;
  document_family_id: string;
  document_name: string;
  document_type: string | null;
  document_version: number;
  document_is_current: boolean;
  source_locator_type: string | null;
  source_locator_value: string | null;
  source_quote: string | null;
  source_verified: boolean;
}

export interface ReviewedPolicyTerm {
  extraction_id: string;
  category: string;
  title: string;
  value: unknown;
  human_status: "approved" | "edited";
  confidence: string;
  reviewed_at: string | null;
  source: PolicyTermSource;
}

export interface PolicyIssueSpot {
  code: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  title: string;
  description: string;
  trigger: Record<string, unknown>;
  required_human_action: string;
  related_extraction_ids: string[];
}

export interface PolicyIntelligenceResponse {
  claim_id: string;
  generated_at: string;
  terms: ReviewedPolicyTerm[];
  issue_spots: PolicyIssueSpot[];
  summary: {
    reviewed_term_count: number;
    current_policy_document_count: number;
    historical_policy_document_count: number;
    issue_count: number;
    high_priority_issue_count: number;
    has_policy_period: boolean;
    has_insured_value_or_limit: boolean;
    has_deductible: boolean;
  };
  disclaimer: string;
}

export interface PolicyExtractionResponse {
  run_id: string;
  claim_id: string;
  document_id: string;
  document_name: string;
  candidate_count: number;
  candidates: Array<{
    extraction_id: string;
    field_path: string;
    category: string;
    title: string;
    value: unknown;
    confidence: string;
    source_locator_type: string | null;
    source_locator_value: string | null;
    source_quote: string;
    human_status: "pending";
  }>;
  review_required: true;
  external_ai_used: false;
}

export type CorrespondenceDirection = "outbound" | "inbound" | "internal";
export type CorrespondenceKind = "document_request" | "follow_up" | "status_update" | "reservation_of_rights" | "settlement" | "general";
export type CorrespondenceStatus = "draft" | "under_review" | "approved" | "rejected" | "sent_externally" | "received_external" | "filed_internal" | "cancelled";
export type CorrespondenceSensitivity = "standard" | "confidential" | "privileged_confidential" | "without_prejudice";
export type CorrespondenceChannel = "email" | "letter" | "portal" | "phone" | "meeting" | "other";

export interface ClaimCorrespondence {
  id: string;
  claim_id: string;
  request_batch_id: string | null;
  created_by_id: string | null;
  reviewed_by_id: string | null;
  sent_by_id: string | null;
  direction: CorrespondenceDirection;
  kind: CorrespondenceKind;
  status: CorrespondenceStatus;
  sensitivity: CorrespondenceSensitivity;
  channel: CorrespondenceChannel | null;
  sender_label: string | null;
  recipient_label: string | null;
  subject: string;
  body: string;
  requirement_ids: string[];
  review_note: string | null;
  external_reference: string | null;
  content_hash: string | null;
  occurred_at: string | null;
  reviewed_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CorrespondenceListResponse { items: ClaimCorrespondence[]; total: number; }

export type AdjustmentStatus = "draft" | "under_review" | "approved" | "rejected";
export type AdjustmentTreatment = "pending" | "included" | "excluded" | "apportioned" | "credit";
export type AdjustmentBasis = "unallocated" | "particular_average" | "general_average" | "sue_and_labour" | "rdc" | "other" | "not_applicable";

export interface AdjustmentLine {
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
  created_at: string;
  updated_at: string;
}

export interface AdjustmentStatement {
  id: string;
  claim_id: string;
  created_by_id: string | null;
  reviewed_by_id: string | null;
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
  review_note: string | null;
  content_hash: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  lines: AdjustmentLine[];
}

export interface AdjustmentListResponse { items: AdjustmentStatement[]; total: number; }

export interface AIProviderActivationApproval {
  id: string;
  activation_request_id: string;
  approver_id: string | null;
  approval_role: "security" | "privacy" | "product";
  action: "approve" | "reject";
  evidence_reference: string | null;
  note: string;
  approved_at: string;
  created_at: string;
}

export interface AIProviderActivationSummary {
  required_approval_count: number;
  approval_count: number;
  independent_approvals_complete: boolean;
  staging_evaluation_authorized: boolean;
  authorization_active: boolean;
  provider_configuration_mutated: false;
  production_authorized: false;
  restricted_documents_authorized: false;
  real_claim_data_authorized: false;
  human_review_required: true;
  key_material_stored: false;
}

export interface AIProviderActivation {
  id: string;
  requested_by_id: string | null;
  finalized_by_id: string | null;
  revoked_by_id: string | null;
  attempt_number: number;
  request_key: string;
  environment: "staging";
  provider: "openai";
  provider_project_label: string;
  model: string;
  prompt_bundle_version: string;
  schema_bundle_version: string;
  data_mode: "synthetic_deidentified";
  allowed_document_types: string[];
  restricted_documents_allowed: false;
  credential_storage_mode: "environment" | "secret_manager";
  max_input_chars: number;
  max_output_tokens: number;
  requests_per_minute: number;
  tokens_per_minute: number;
  monthly_spend_limit_cents: number;
  spend_alert_thresholds: number[];
  retention_mode: string;
  data_residency_region: string;
  security_owner_label: string;
  privacy_owner_label: string;
  product_owner_label: string;
  incident_owner_label: string;
  kill_switch_owner_label: string;
  credential_control_reference: string;
  spend_limit_reference: string;
  data_processing_reference: string;
  kill_switch_reference: string;
  evaluation_expires_at: string;
  status: string;
  outcome: string | null;
  decision_note: string | null;
  decision_hash: string | null;
  decided_at: string | null;
  revoked_at: string | null;
  revocation_note: string | null;
  approvals: AIProviderActivationApproval[];
  summary: AIProviderActivationSummary;
  created_at: string;
}

export interface AIDocumentEligibility {
  id: string;
  activation_request_id: string;
  claim_id: string;
  document_id: string;
  attested_by_id: string | null;
  revoked_by_id: string | null;
  attestation_number: number;
  data_mode: "synthetic" | "deidentified";
  document_type: string;
  confidentiality_level: string;
  evidence_reference: string;
  note: string;
  snapshot_hash: string;
  status: string;
  attested_at: string;
  revoked_at: string | null;
  revocation_note: string | null;
  created_at: string;
}

export interface AIGovernanceDashboard {
  activation_requests: AIProviderActivation[];
  document_eligibility: AIDocumentEligibility[];
}

export interface AIEvaluationCase {
  id: string;
  suite_id: string;
  submitted_by_id: string | null;
  case_key: string;
  document_type: "chief_engineer_report" | "engine_log";
  scenario_type: "baseline" | "prompt_injection" | "malformed_input" | "cross_tenant" | "restricted_data";
  data_mode: "synthetic" | "deidentified";
  result: "pass" | "fail";
  field_true_positive: number;
  field_false_positive: number;
  field_false_negative: number;
  extracted_claim_count: number;
  unsupported_claim_count: number;
  source_quote_checked_count: number;
  source_quote_valid_count: number;
  human_approved_count: number;
  human_edited_count: number;
  human_rejected_count: number;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  observed_provider_cost_microusd: number;
  boundary_control_passed: boolean;
  evidence_reference: string;
  note: string;
  result_hash: string;
  executed_at: string;
  created_at: string;
}

export interface AIEvaluationReview {
  id: string;
  suite_id: string;
  reviewer_id: string | null;
  review_role: "quality" | "risk";
  action: "approve" | "reject";
  evidence_reference: string | null;
  note: string;
  reviewed_at: string;
  created_at: string;
}

export interface AIEvaluationSuite {
  id: string;
  activation_request_id: string;
  requested_by_id: string | null;
  finalized_by_id: string | null;
  revoked_by_id: string | null;
  attempt_number: number;
  suite_key: string;
  benchmark_profile: "quality_safety_cost_v1";
  activation_model: string;
  prompt_bundle_version: string;
  schema_bundle_version: string;
  max_input_chars: number;
  max_output_tokens: number;
  data_mode: "synthetic_deidentified";
  thresholds: Record<string, number | string[]>;
  status: string;
  outcome: string | null;
  metrics: Record<string, unknown> | null;
  failure_reasons: string[];
  evaluation_hash: string | null;
  evaluation_note: string | null;
  evaluated_at: string | null;
  decision_note: string | null;
  decision_hash: string | null;
  decided_at: string | null;
  promotion_expires_at: string | null;
  revoked_at: string | null;
  revocation_note: string | null;
  summary: {
    case_count: number;
    required_case_count: number;
    thresholds_passed: boolean;
    independent_reviews_complete: boolean;
    shared_staging_promotion_recorded: boolean;
    promotion_active: boolean;
    raw_content_stored: false;
    provider_configuration_mutated: false;
    calculated_provider_billing: false;
    production_authorized: false;
    restricted_documents_authorized: false;
    real_claim_data_authorized: false;
    autonomous_claim_decisions_authorized: false;
    human_review_required: true;
  };
  cases: AIEvaluationCase[];
  reviews: AIEvaluationReview[];
  created_at: string;
}

export interface AIEvaluationDashboard { suites: AIEvaluationSuite[]; }
