import type { Locale } from "./i18n";
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

function numberLocale(locale: Locale) {
  return locale === "fa" ? "fa-IR-u-nu-latn" : "en-US";
}

function dateLocale(locale: Locale) {
  // Persian UI retains the authoritative Gregorian date while localizing month text.
  return locale === "fa" ? "fa-IR-u-ca-gregory-nu-latn" : "en-GB";
}

export function formatMoney(value: string | number | null, currency = "USD", locale: Locale = "en") {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat(numberLocale(locale), { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString(numberLocale(locale))}`;
  }
}

export function formatDate(value: string | null | undefined, locale: Locale = "en") {
  if (!value) return "—";
  const looksLikeDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value.trim());
  const date = new Date(looksLikeDateOnly ? `${value.trim()}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(dateLocale(locale), { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

export function formatDateTime(value: string | null | undefined, locale: Locale = "en") {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(dateLocale(locale), {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function humanizeFieldLabel(value: string) {
  const leaf = value.split(".").at(-1) ?? value;
  return leaf
    .replace(/\[(\d+)\]/g, " $1")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatStructuredValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString("en-US");
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(formatStructuredValue).join(", ");
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.raw !== null && record.raw !== undefined && String(record.raw).trim()) return String(record.raw);
    if (record.value !== null && record.value !== undefined) {
      const unit = record.unit ? ` ${String(record.unit)}` : "";
      const rawValue = typeof record.value === "number" ? record.value.toLocaleString("en-US") : String(record.value);
      return `${rawValue}${unit}`.trim();
    }
    const readable = Object.entries(record)
      .filter(([key]) => !["id", "extraction_id", "document_id"].includes(key))
      .map(([key, nested]) => `${humanizeFieldLabel(key)}: ${formatStructuredValue(nested)}`)
      .join(" · ");
    return readable || "—";
  }
  return String(value);
}
