import { API_BASE, ApiError } from "./api";
import type {
  ClaimCorrespondence,
  CorrespondenceChannel,
  CorrespondenceDirection,
  CorrespondenceKind,
  CorrespondenceSensitivity,
} from "./types";

export interface CorrespondenceReviewDecision {
  id: string;
  correspondence_id: string;
  reviewed_by_id: string | null;
  correspondence_state_fingerprint: string;
  state_version: number;
  review_number: number;
  action: "approve" | "reject";
  note: string;
  content_hash: string | null;
  previous_review_hash: string | null;
  review_hash: string;
  reviewed_at: string;
}

export interface GovernedClaimCorrespondence extends ClaimCorrespondence {
  state_fingerprint: string;
  state_version: number;
  sent_review_hash: string | null;
  review_state: "none" | "current" | "stale" | "legacy_unbound";
  latest_review: CorrespondenceReviewDecision | null;
  review_history: CorrespondenceReviewDecision[];
}

export interface GovernedCorrespondenceListResponse {
  items: GovernedClaimCorrespondence[];
  total: number;
}

async function correspondenceFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      // Preserve a safe generic error for non-JSON responses.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function listClaimCorrespondence(claimId: string) {
  return correspondenceFetch<GovernedCorrespondenceListResponse>(`/claims/${claimId}/correspondence`);
}

export function createClaimCorrespondence(claimId: string, payload: {
  direction: CorrespondenceDirection;
  kind: CorrespondenceKind;
  sensitivity: CorrespondenceSensitivity;
  sender_label?: string | null;
  recipient_label?: string | null;
  subject: string;
  body: string;
  channel?: CorrespondenceChannel | null;
  external_reference?: string | null;
}) {
  return correspondenceFetch<GovernedClaimCorrespondence>(`/claims/${claimId}/correspondence`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateClaimCorrespondence(
  claimId: string,
  item: GovernedClaimCorrespondence,
  payload: Partial<{
    kind: CorrespondenceKind;
    sensitivity: CorrespondenceSensitivity;
    sender_label: string | null;
    recipient_label: string | null;
    subject: string;
    body: string;
  }>,
) {
  return correspondenceFetch<GovernedClaimCorrespondence>(`/claims/${claimId}/correspondence/${item.id}`, {
    method: "PATCH",
    body: JSON.stringify({
      ...payload,
      expected_state_fingerprint: item.state_fingerprint,
      expected_state_version: item.state_version,
    }),
  });
}

export function submitClaimCorrespondence(claimId: string, item: GovernedClaimCorrespondence) {
  return correspondenceFetch<GovernedClaimCorrespondence>(`/claims/${claimId}/correspondence/${item.id}/submit`, {
    method: "POST",
    body: JSON.stringify({
      expected_state_fingerprint: item.state_fingerprint,
      expected_state_version: item.state_version,
    }),
  });
}

export function reviewClaimCorrespondence(
  claimId: string,
  item: GovernedClaimCorrespondence,
  action: "approve" | "reject",
  note: string,
) {
  return correspondenceFetch<GovernedClaimCorrespondence>(`/claims/${claimId}/correspondence/${item.id}/${action}`, {
    method: "POST",
    body: JSON.stringify({
      note,
      expected_state_fingerprint: item.state_fingerprint,
      expected_state_version: item.state_version,
      confirm_re_review: item.review_history.length > 0,
    }),
  });
}

export function markClaimCorrespondenceSent(
  claimId: string,
  item: GovernedClaimCorrespondence,
  payload: {
    confirm_sent: boolean;
    channel: CorrespondenceChannel;
    external_reference?: string | null;
  },
) {
  if (!item.latest_review || item.latest_review.action !== "approve") {
    throw new ApiError(409, "A current approved review is required before external dispatch can be recorded.");
  }
  return correspondenceFetch<GovernedClaimCorrespondence>(`/claims/${claimId}/correspondence/${item.id}/mark-sent`, {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      expected_state_fingerprint: item.state_fingerprint,
      expected_state_version: item.state_version,
      expected_review_hash: item.latest_review.review_hash,
    }),
  });
}
