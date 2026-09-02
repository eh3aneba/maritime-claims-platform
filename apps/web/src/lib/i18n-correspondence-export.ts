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
  if (locale === "fa" && fa[value]) return fa[value];
  return value.replaceAll("_", " ");
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
