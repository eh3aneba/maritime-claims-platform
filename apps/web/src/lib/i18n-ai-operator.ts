import type { Locale } from "./i18n";

export function aiT(locale: Locale, en: string, fa: string): string {
  return locale === "fa" ? fa : en;
}

const faLabels: Record<string, string> = {
  all: "همه",
  pending: "در انتظار",
  approved: "تأییدشده",
  edited: "ویرایش‌شده",
  rejected: "ردشده",
  fact: "واقعیت",
  opinion: "نظر",
  inference: "استنباط",
  needs_attention: "نیازمند توجه",
  routine: "عادی",
  staging_authorized: "مجاز برای محیط آزمایشی",
  decision_ready: "آماده تصمیم",
  eligible: "واجد شرایط",
  held: "متوقف‌شده",
  revoked: "لغوشده",
  pending_approvals: "در انتظار تأییدها",
  security: "امنیت",
  privacy: "حریم خصوصی",
  product: "محصول",
  approve: "تأیید",
  edit: "ویرایش",
  reject: "رد",
  synthetic: "مصنوعی",
  deidentified: "ناشناس‌سازی‌شده",
  review_ready: "آماده بازبینی",
  promotion_ready: "آماده ارتقا",
  staging_promoted: "در محیط آزمایشی ارتقا یافته",
  failed: "ناموفق",
  review_rejected: "بازبینی ردشده",
  collecting: "در حال جمع‌آوری",
  pass: "قبول",
  fail: "رد",
  quality: "کیفیت",
  risk: "ریسک",
  baseline: "خط پایه",
  prompt_injection: "تزریق پرامپت",
  malformed_input: "ورودی نامعتبر",
  cross_tenant: "بین‌سازمانی",
  restricted_data: "داده محدودشده",
  chief_engineer_report: "گزارش مهندس ارشد",
  engine_log: "لاگ موتور",
  document_processing: "پردازش سند",
  claim_qa_synthesis: "ترکیب پرسش‌وپاسخ پرونده",
  completed: "تکمیل‌شده",
  not_applicable: "نامرتبط",
  blocked: "مسدود",
  fallback: "مسیر جایگزین",
  clear: "بدون هشدار",
  low: "کم",
  medium: "متوسط",
  high: "زیاد",
  critical: "بحرانی",
  cost: "هزینه",
  availability: "دسترس‌پذیری",
  reliability: "قابلیت اطمینان",
  other: "سایر",
  enabled: "فعال",
  disabled: "غیرفعال",
  queued: "در صف",
  attempting: "در حال تلاش",
  delivered: "تحویل‌شده",
  dead_letter: "صف بن‌بست",
  content_free: "بدون محتوای خام",
  output_candidate_count: "تعداد خروجی‌های کاندید",
  human_edit_count: "تعداد ویرایش‌های انسانی",
  unsupported_output_count: "تعداد خروجی‌های بدون پشتوانه",
  source_grounded_output_count: "تعداد خروجی‌های مستند به منبع",
  source_grounding_total_count: "کل خروجی‌های بررسی‌شده برای استناد",
  latency_ms: "تأخیر (ms)",
  observed_provider_cost_microusd: "هزینه مشاهده‌شده ارائه‌دهنده (µUSD)",
};

export function aiLabel(locale: Locale, value: string | null | undefined): string {
  if (!value) return "—";
  const normalized = value.replace(/^ai_operations\./, "");
  // English is the compatibility baseline: preserve the pre-localization enum
  // presentation exactly (underscores become spaces, casing/content otherwise unchanged).
  if (locale === "en") return normalized.replaceAll("_", " ");
  return faLabels[normalized] ?? normalized.replaceAll("_", " ");
}

export function aiBoolean(locale: Locale, value: boolean): string {
  return aiT(locale, value ? "Yes" : "No", value ? "بله" : "خیر");
}
