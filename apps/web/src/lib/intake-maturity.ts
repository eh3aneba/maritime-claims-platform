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
    retryProcessing: "Review source & retry processing",
    retrying: "Retrying…",
    checkStatus: "Check status",
    checkingStatus: "Checking…",
    draftReference: "Draft reference",
    processingLonger: "Processing is taking longer than expected. The draft remains saved and resumable in this browser session; use Check status instead of uploading the source again.",
    processingRestored: "A saved intake draft was restored. Its current processing status is shown below.",
    processingStillRunning: "Processing is still running. The draft remains saved; check again later without re-uploading the source.",
    statusCheckError: "Could not refresh the saved intake status.",
    loadTypesError: "Could not load the controlled document-type registry.",
    retryError: "Could not restart intake processing.",
  },
  fa: {
    documentType: "نوع سند",
    classificationAdvisory: "طبقه‌بندی پیشنهادی",
    classificationBasis: "مبنای پیشنهاد",
    selectDocumentType: "نوع سند تأییدشده را انتخاب کنید",
    correctionRequired: "پیش از تأیید، نوع سند را بررسی و انتخاب کنید.",
    retryProcessing: "بررسی منبع و پردازش مجدد",
    retrying: "در حال پردازش مجدد…",
    checkStatus: "بررسی وضعیت",
    checkingStatus: "در حال بررسی…",
    draftReference: "شناسه پیش‌نویس",
    processingLonger: "پردازش بیش از حد انتظار طول کشیده است. پیش‌نویس در همین نشست مرورگر ذخیره و قابل ادامه است؛ به‌جای بارگذاری مجدد سند، وضعیت را بررسی کنید.",
    processingRestored: "پیش‌نویس ذخیره‌شده بازیابی شد. وضعیت فعلی پردازش در پایین نمایش داده می‌شود.",
    processingStillRunning: "پردازش هنوز ادامه دارد. پیش‌نویس ذخیره است؛ بعداً دوباره وضعیت را بررسی کنید و سند را مجدداً بارگذاری نکنید.",
    statusCheckError: "به‌روزرسانی وضعیت پیش‌نویس ذخیره‌شده ممکن نشد.",
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
