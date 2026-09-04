import { API_BASE, ApiError } from "./api";
import type { ClaimIntakeDraft } from "./types";

export interface ClaimIntakeDocumentTypeRegistry {
  items: string[];
  default: string;
  unknown_requires_human_choice: boolean;
}

const DOCUMENT_TYPE_LABELS: Record<string, { en: string; fa: string }> = {
  claim_notification: { en: "Claim notification / FNOL", fa: "اعلام خسارت / FNOL" },
  chief_engineer_report: { en: "Chief Engineer report", fa: "گزارش مهندس ارشد" },
  survey_report: { en: "Survey report", fa: "گزارش بازدید / Survey" },
  engine_log: { en: "Engine log", fa: "لاگ موتور" },
  running_hours_record: { en: "Running-hours record", fa: "سوابق ساعات کارکرد" },
  pms_record: { en: "PMS / maintenance record", fa: "سوابق PMS / نگهداری" },
  workshop_report: { en: "Workshop report", fa: "گزارش کارگاه" },
  quotation: { en: "Quotation", fa: "پیشنهاد قیمت" },
  invoice: { en: "Invoice", fa: "صورتحساب" },
  class_report: { en: "Class report", fa: "گزارش رده‌بندی" },
  repair_report: { en: "Repair report", fa: "گزارش تعمیرات" },
  correspondence: { en: "Correspondence", fa: "مکاتبات" },
  other: { en: "Other H&M evidence", fa: "سایر مدارک H&M" },
};

const TEXT = {
  en: {
    documentType: "Document type",
    classificationAdvisory: "Suggested classification",
    classificationBasis: "Basis",
    selectDocumentType: "Select the reviewed document type",
    correctionRequired: "Review and select the document type before approval.",
    retryProcessing: "Retry processing",
    retrying: "Retrying…",
    processingLonger: "Processing is taking longer than expected. The draft remains saved; refresh or retry only if it reaches a failed state.",
    loadTypesError: "Could not load the controlled document-type registry.",
    retryError: "Could not restart intake processing.",
  },
  fa: {
    documentType: "نوع سند",
    classificationAdvisory: "طبقه‌بندی پیشنهادی",
    classificationBasis: "مبنای پیشنهاد",
    selectDocumentType: "نوع سند تأییدشده را انتخاب کنید",
    correctionRequired: "پیش از تأیید، نوع سند را بررسی و انتخاب کنید.",
    retryProcessing: "پردازش مجدد",
    retrying: "در حال پردازش مجدد…",
    processingLonger: "پردازش بیش از حد انتظار طول کشیده است. پیش‌نویس ذخیره شده؛ فقط در صورت ورود به وضعیت خطا، پردازش مجدد را اجرا کنید.",
    loadTypesError: "فهرست کنترل‌شده انواع سند بارگذاری نشد.",
    retryError: "شروع مجدد پردازش امکان‌پذیر نبود.",
  },
} as const;

export type IntakeMaturityTextKey = keyof typeof TEXT.en;

export function intakeMaturityT(locale: "en" | "fa", key: IntakeMaturityTextKey): string {
  return TEXT[locale][key];
}

export function intakeDocumentTypeLabel(locale: "en" | "fa", code: string): string {
  return DOCUMENT_TYPE_LABELS[code]?.[locale] ?? code.replaceAll("_", " ");
}

async function responseDetail(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json();
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function listClaimIntakeDocumentTypes(): Promise<ClaimIntakeDocumentTypeRegistry> {
  const response = await fetch(`${API_BASE}/claim-intake/document-types`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      await responseDetail(response, `Document type registry failed (${response.status})`),
    );
  }
  return response.json() as Promise<ClaimIntakeDocumentTypeRegistry>;
}

export async function retryClaimIntakeDraft(id: string): Promise<ClaimIntakeDraft> {
  const response = await fetch(`${API_BASE}/claim-intake/drafts/${id}/retry`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      await responseDetail(response, `Intake retry failed (${response.status})`),
    );
  }
  return response.json() as Promise<ClaimIntakeDraft>;
}
