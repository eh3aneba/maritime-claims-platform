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
