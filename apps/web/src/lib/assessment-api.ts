import { API_BASE, ApiError } from "./api";
import type { AssessmentSection, InitialAssessment } from "./types";

export type AssessmentSourceState = "current" | "stale" | "legacy_unbound";

export type SourceAwareInitialAssessment = InitialAssessment & {
  source_fingerprint: string | null;
  current_source_fingerprint: string | null;
  source_state: AssessmentSourceState;
  approved_content_hash: string | null;
};

async function assessmentFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (payload.detail && typeof payload.detail.message === "string") detail = payload.detail.message;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function getInitialAssessment(claimId: string) {
  return assessmentFetch<SourceAwareInitialAssessment | null>(`/claims/${claimId}/initial-assessment`);
}

export function generateInitialAssessment(
  claimId: string,
  payload: { allow_if_not_ready: boolean; override_reason?: string | null },
) {
  return assessmentFetch<SourceAwareInitialAssessment>(`/claims/${claimId}/initial-assessment/generate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function reviewAssessmentSection(
  claimId: string,
  sectionId: string,
  payload: { action: "approve" | "edit"; text?: string | null; expected_source_fingerprint: string },
) {
  return assessmentFetch<AssessmentSection>(
    `/claims/${claimId}/initial-assessment/sections/${sectionId}/review`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function approveInitialAssessment(
  claimId: string,
  assessmentId: string,
  expectedSourceFingerprint: string,
  note?: string,
) {
  return assessmentFetch<SourceAwareInitialAssessment>(
    `/claims/${claimId}/initial-assessment/${assessmentId}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        note: note || null,
        expected_source_fingerprint: expectedSourceFingerprint,
      }),
    },
  );
}
