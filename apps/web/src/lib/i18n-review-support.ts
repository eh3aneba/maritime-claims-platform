import type { Locale } from "./i18n";
import type { CostReviewStatus } from "./types";

export function reviewT(locale: Locale, en: string, fa: string): string {
  return locale === "fa" ? fa : en;
}

export function supportStatusLabel(locale: Locale, value: string): string {
  const fa: Record<string, string> = {
    triggered: "فعال",
    insufficient_evidence: "شواهد ناکافی",
    not_applicable: "نامرتبط",
    clear: "بدون هشدار",
    open: "باز",
    explained: "توضیح داده‌شده",
    resolved: "حل‌شده",
  };
  if (locale === "fa" && fa[value]) return fa[value];
  return value.replaceAll("_", " ");
}

export function severityLabel(locale: Locale, value: string | null | undefined): string {
  if (!value) return reviewT(locale, "Not available", "موجود نیست");
  const en: Record<string, string> = { low: "Low", medium: "Medium", high: "High", critical: "Critical" };
  const fa: Record<string, string> = { low: "کم", medium: "متوسط", high: "زیاد", critical: "بحرانی" };
  return (locale === "fa" ? fa : en)[value] ?? value.replaceAll("_", " ");
}

export function urgencyLabel(locale: Locale, value: string): string {
  const fa: Record<string, string> = { low: "کم", medium: "متوسط", high: "زیاد", critical: "بحرانی" };
  if (locale === "fa" && fa[value]) return fa[value];
  return value.replaceAll("_", " ");
}

export function evaluationKindLabel(locale: Locale, value: string): string {
  const fa: Record<string, string> = { severity: "شدت", reserve: "ذخیره", recovery: "بازیافت", timebar: "مهلت زمانی" };
  if (locale === "fa" && fa[value]) return fa[value];
  return value.replaceAll("_", " ");
}

export function decisionActionLabel(locale: Locale, value: string): string {
  const en: Record<string, string> = {
    accept: "Accept",
    edit: "Edit",
    dismiss: "Dismiss",
    not_applicable: "Not applicable",
  };
  const fa: Record<string, string> = {
    accept: "پذیرش",
    edit: "ویرایش برداشت انسانی",
    dismiss: "رد برای این بازبینی",
    not_applicable: "نامرتبط",
  };
  return (locale === "fa" ? fa : en)[value] ?? value.replaceAll("_", " ");
}

export function costStatusLabel(locale: Locale, value: CostReviewStatus): string {
  const en: Record<CostReviewStatus, string> = {
    claimed: "Claimed",
    under_review: "Under review",
    potentially_recoverable: "Potentially recoverable",
    potentially_non_recoverable: "Potentially non-recoverable",
    accepted: "Accepted",
    rejected: "Rejected",
    paid: "Paid",
  };
  const fa: Record<CostReviewStatus, string> = {
    claimed: "مطالبه‌شده",
    under_review: "در حال بازبینی",
    potentially_recoverable: "احتمالاً قابل بازیافت",
    potentially_non_recoverable: "احتمالاً غیرقابل بازیافت",
    accepted: "پذیرفته‌شده",
    rejected: "ردشده",
    paid: "پرداخت‌شده",
  };
  return (locale === "fa" ? fa : en)[value];
}

export function technicalStatusLabel(locale: Locale, value: string): string {
  const fa: Record<string, string> = {
    open: "باز",
    review_required: "نیازمند بازبینی",
    evidence_gap: "شکاف شواهد",
    supported: "پشتیبانی‌شده",
    not_supported: "پشتیبانی‌نشده",
    not_applicable: "نامرتبط",
  };
  if (locale === "fa" && fa[value]) return fa[value];
  return value.replaceAll("_", " ");
}

export function maintenanceLabel(locale: Locale, key: string, fallback: string): string {
  const en: Record<string, string> = {
    "maintenance.interval_extension_details": "Interval extension evidence",
    "maintenance.last_overhaul_date": "Last overhaul date",
    "maintenance.recommended_overhaul_interval": "Recommended overhaul interval",
    "maintenance.total_running_hours": "Total running hours",
    "maintenance.overhaul_deferred": "Overhaul deferred",
    "maintenance.pms_status": "PMS status",
    "maintenance.running_hours_since_overhaul": "Running hours since overhaul",
    "workshop.repairable": "Workshop considers unit repairable",
  };
  const fa: Record<string, string> = {
    "maintenance.interval_extension_details": "شواهد تمدید فاصله سرویس",
    "maintenance.last_overhaul_date": "تاریخ آخرین اورهال",
    "maintenance.recommended_overhaul_interval": "فاصله پیشنهادی اورهال",
    "maintenance.total_running_hours": "کل ساعات کارکرد",
    "maintenance.overhaul_deferred": "اورهال به تعویق افتاده",
    "maintenance.pms_status": "وضعیت PMS",
    "maintenance.running_hours_since_overhaul": "ساعات کارکرد از آخرین اورهال",
    "workshop.repairable": "نظر کارگاه درباره قابل تعمیر بودن واحد",
  };
  return (locale === "fa" ? fa : en)[key] ?? fallback;
}
