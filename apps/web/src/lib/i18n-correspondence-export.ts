import type { Locale } from "./i18n";
import type {
  CorrespondenceChannel,
  CorrespondenceDirection,
  CorrespondenceKind,
  CorrespondenceSensitivity,
} from "./types";

export function correspondenceT(locale: Locale, en: string, fa: string): string {
  return locale === "fa" ? fa : en;
}

export function correspondenceStatusLabel(locale: Locale, value: string): string {
  const en: Record<string, string> = {
    draft: "Draft",
    rejected: "Rejected",
    under_review: "Under review",
    approved: "Approved",
    sent_externally: "External dispatch recorded",
    received_external: "Received externally",
    filed_internal: "Filed internally",
    cancelled: "Cancelled",
  };
  const fa: Record<string, string> = {
    draft: "پیش‌نویس",
    rejected: "ردشده",
    under_review: "در حال بازبینی",
    approved: "تأییدشده",
    sent_externally: "ارسال خارجی ثبت‌شده",
    received_external: "دریافت خارجی",
    filed_internal: "ثبت داخلی",
    cancelled: "لغوشده",
  };
  const dictionary = locale === "fa" ? fa : en;
  return dictionary[value] ?? value.replaceAll("_", " ");
}

export function correspondenceReviewStateLabel(locale: Locale, value: string): string {
  const en: Record<string, string> = {
    none: "Not reviewed yet",
    current: "Review matches current state",
    stale: "Historical review — current state needs review",
    legacy_unbound: "Legacy review — exact context not bound",
  };
  const fa: Record<string, string> = {
    none: "هنوز بازبینی نشده",
    current: "بازبینی با وضعیت فعلی منطبق است",
    stale: "بازبینی تاریخی است — وضعیت فعلی نیاز به بازبینی دارد",
    legacy_unbound: "بازبینی قدیمی است — زمینه دقیق به آن متصل نشده",
  };
  const dictionary = locale === "fa" ? fa : en;
  return dictionary[value] ?? value.replaceAll("_", " ");
}

export function correspondenceReviewActionLabel(locale: Locale, value: "approve" | "reject"): string {
  if (locale === "fa") return value === "approve" ? "تأیید" : "رد";
  return value === "approve" ? "Approved" : "Rejected";
}

export function correspondenceDirectionLabel(locale: Locale, value: CorrespondenceDirection): string {
  const fa: Record<CorrespondenceDirection, string> = {
    outbound: "خروجی",
    inbound: "ورودی",
    internal: "داخلی",
  };
  return locale === "fa" ? fa[value] : value;
}

export function correspondenceDirectionOptionLabel(locale: Locale, value: CorrespondenceDirection): string {
  const en: Record<CorrespondenceDirection, string> = {
    outbound: "Outbound draft",
    inbound: "Inbound record",
    internal: "Internal note",
  };
  const fa: Record<CorrespondenceDirection, string> = {
    outbound: "پیش‌نویس خروجی",
    inbound: "رکورد ورودی",
    internal: "یادداشت داخلی",
  };
  return (locale === "fa" ? fa : en)[value];
}

export function correspondenceKindLabel(locale: Locale, value: CorrespondenceKind): string {
  const fa: Record<CorrespondenceKind, string> = {
    document_request: "درخواست سند",
    follow_up: "پیگیری",
    status_update: "به‌روزرسانی وضعیت",
    reservation_of_rights: "رزرو حقوق",
    settlement: "تسویه",
    general: "عمومی",
  };
  if (locale === "fa") return fa[value];
  return value.replaceAll("_", " ");
}

export function correspondenceKindOptionLabel(locale: Locale, value: CorrespondenceKind): string {
  const en: Record<CorrespondenceKind, string> = {
    document_request: "Document request",
    follow_up: "Follow-up",
    status_update: "Status update",
    reservation_of_rights: "Reservation of rights",
    settlement: "Settlement",
    general: "General",
  };
  const fa: Record<CorrespondenceKind, string> = {
    document_request: "درخواست سند",
    follow_up: "پیگیری",
    status_update: "به‌روزرسانی وضعیت",
    reservation_of_rights: "رزرو حقوق",
    settlement: "تسویه",
    general: "عمومی",
  };
  return (locale === "fa" ? fa : en)[value];
}

export function correspondenceSensitivityLabel(locale: Locale, value: CorrespondenceSensitivity): string {
  const en: Record<CorrespondenceSensitivity, string> = {
    standard: "Standard",
    confidential: "Confidential",
    privileged_confidential: "Privileged & Confidential",
    without_prejudice: "Without Prejudice",
  };
  const fa: Record<CorrespondenceSensitivity, string> = {
    standard: "استاندارد",
    confidential: "محرمانه",
    privileged_confidential: "محرمانه و دارای امتیاز حقوقی",
    without_prejudice: "Without Prejudice",
  };
  return (locale === "fa" ? fa : en)[value];
}

export function correspondenceChannelLabel(locale: Locale, value: CorrespondenceChannel): string {
  const en: Record<CorrespondenceChannel, string> = {
    email: "Email",
    letter: "Letter",
    portal: "Portal",
    phone: "Phone",
    meeting: "Meeting",
    other: "Other",
  };
  const fa: Record<CorrespondenceChannel, string> = {
    email: "ایمیل",
    letter: "نامه",
    portal: "پرتال",
    phone: "تلفن",
    meeting: "جلسه",
    other: "سایر",
  };
  return (locale === "fa" ? fa : en)[value];
}
