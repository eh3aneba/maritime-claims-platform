import type { ClaimPriority, ClaimStatus } from "./types";

export const statusLabel: Record<ClaimStatus, string> = {
  new: "New",
  triage: "Triage",
  awaiting_documents: "Awaiting documents",
  investigation: "Investigation",
  technical_review: "Technical review",
  financial_review: "Financial review",
  coverage_review: "Coverage review",
  negotiation: "Negotiation",
  settlement: "Settlement",
  recovery: "Recovery",
  closed: "Closed",
  on_hold: "On hold",
  litigation: "Litigation",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

export const priorityLabel: Record<ClaimPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export function formatMoney(value: string | number | null, currency = "USD") {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString("en-US")}`;
  }
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}
