import type { Claim, ClaimListResponse, CurrentUser, Vessel, VesselListResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

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
