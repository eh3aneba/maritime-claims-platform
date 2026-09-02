import type { Locale } from "./i18n";

const en = {
  "backToClaim": "← Back to claim",
  "title": "Claim chronology",
  "subtitle": "Human-reviewed evidence aligned into a single timeline. Conflicts are review flags only; the system does not decide which source is factually correct.",
  "loading": "Loading chronology…",
  "loadError": "Chronology could not be loaded.",
  "rebuildError": "Chronology could not be rebuilt.",
  "conflictUpdateError": "Conflict could not be updated.",
  "noteRequired": "Add a short explanation before resolving a conflict.",
  "refreshing": "Refreshing…",
  "buildRefresh": "Build / refresh chronology",
  "metric.events": "Timeline events",
  "metric.openConflicts": "Open evidence conflicts",
  "metric.sources": "Reviewed source documents",
  "section.chronology": "Chronology",
  "section.chronologyHelp": "Events within ten minutes may be clustered when they describe the same event type. For display purposes only, an Engine Log timestamp may be used as the canonical time inside a compatible cluster; this does not determine which evidence is true.",
  "timeNotStated": "Time not stated",
  "relativeUndated": "Relative / undated",
  "eventImportance": "Event importance: {value}",
  "source.one": "Source",
  "source.many": "Sources",
  "sourcesEvidence": "Sources ({sources}) · Evidence fields ({evidence})",
  "sourceVerified": "Source verified",
  "manualVerification": "Manual verification",
  "value": "Value",
  "emptyChronology": "No chronology has been built from reviewed evidence yet.",
  "section.conflicts": "Evidence conflicts",
  "section.conflictsHelp": "A conflict is a review flag, not a finding about which evidence is true.",
  "conflictSeverity": "Conflict severity: {value}",
  "difference": "Difference",
  "minutes": "minutes",
  "notePlaceholder": "Explain how this difference should be understood…",
  "action.explain": "Explain",
  "action.acceptDifference": "Accept difference",
  "action.resolve": "Resolve",
  "action.irrelevant": "Mark irrelevant",
  "reviewNote": "Review note",
  "emptyConflicts": "No evidence conflicts are currently recorded.",
  "materiality.low": "Low",
  "materiality.medium": "Medium",
  "materiality.high": "High",
  "materiality.critical": "Critical",
  "status.open": "Open",
  "status.explained": "Explained",
  "status.accepted_difference": "Accepted difference",
  "status.resolved": "Resolved",
  "status.irrelevant": "Irrelevant",
  "measurement.rpm": "RPM",
  "measurement.engine_load": "Engine load",
  "measurement.turbocharger_speed": "Turbocharger speed",
  "measurement.exhaust_temperature": "Exhaust temperature",
  "measurement.lube_oil_pressure": "Lube oil pressure",
  "conflictType.timestamp": "Timestamp difference",
  "conflictType.date": "Date difference",
  "conflictType.measurement": "Measurement difference",
  "conflictType.value": "Value difference",
} as const;

export type ChronologyKey = keyof typeof en;

const fa: Record<ChronologyKey, string> = {
  "backToClaim": "→ بازگشت به پرونده",
  "title": "خط زمانی پرونده",
  "subtitle": "شواهد بازبینی‌شده انسانی در یک خط زمانی واحد کنار هم قرار می‌گیرند. تعارض‌ها فقط پرچم بازبینی هستند و سیستم تعیین نمی‌کند کدام منبع از نظر واقعی درست است.",
  "loading": "در حال بارگذاری خط زمانی…",
  "loadError": "خط زمانی بارگذاری نشد.",
  "rebuildError": "بازسازی خط زمانی انجام نشد.",
  "conflictUpdateError": "تعارض به‌روزرسانی نشد.",
  "noteRequired": "پیش از تعیین وضعیت تعارض، یک توضیح کوتاه وارد کنید.",
  "refreshing": "در حال به‌روزرسانی…",
  "buildRefresh": "ساخت / به‌روزرسانی خط زمانی",
  "metric.events": "رویدادهای خط زمانی",
  "metric.openConflicts": "تعارض‌های باز شواهد",
  "metric.sources": "اسناد منبع بازبینی‌شده",
  "section.chronology": "خط زمانی",
  "section.chronologyHelp": "رویدادهایی که حداکثر ده دقیقه فاصله دارند، در صورت توصیف یک نوع رویداد ممکن است در یک خوشه نمایش داده شوند. صرفاً برای نمایش، زمان Engine Log می‌تواند در یک خوشه سازگار به‌عنوان زمان مرجع نمایش استفاده شود؛ این موضوع تعیین نمی‌کند کدام شاهد حقیقت دارد.",
  "timeNotStated": "زمان ذکر نشده",
  "relativeUndated": "نسبی / بدون تاریخ",
  "eventImportance": "اهمیت رویداد: {value}",
  "source.one": "منبع",
  "source.many": "منابع",
  "sourcesEvidence": "منابع ({sources}) · فیلدهای شاهد ({evidence})",
  "sourceVerified": "منبع تأیید شده",
  "manualVerification": "نیازمند تأیید دستی",
  "value": "مقدار",
  "emptyChronology": "هنوز از شواهد بازبینی‌شده خط زمانی ساخته نشده است.",
  "section.conflicts": "تعارض‌های شواهد",
  "section.conflictsHelp": "تعارض فقط یک پرچم بازبینی است و به معنی تشخیص درست بودن یکی از شواهد نیست.",
  "conflictSeverity": "شدت تعارض: {value}",
  "difference": "اختلاف",
  "minutes": "دقیقه",
  "notePlaceholder": "توضیح دهید این اختلاف چگونه باید درک شود…",
  "action.explain": "توضیح",
  "action.acceptDifference": "پذیرش اختلاف",
  "action.resolve": "حل تعارض",
  "action.irrelevant": "نامرتبط",
  "reviewNote": "یادداشت بازبینی",
  "emptyConflicts": "در حال حاضر تعارضی برای شواهد ثبت نشده است.",
  "materiality.low": "کم",
  "materiality.medium": "متوسط",
  "materiality.high": "زیاد",
  "materiality.critical": "بحرانی",
  "status.open": "باز",
  "status.explained": "توضیح داده‌شده",
  "status.accepted_difference": "اختلاف پذیرفته‌شده",
  "status.resolved": "حل‌شده",
  "status.irrelevant": "نامرتبط",
  "measurement.rpm": "RPM",
  "measurement.engine_load": "بار موتور",
  "measurement.turbocharger_speed": "سرعت توربوشارژر",
  "measurement.exhaust_temperature": "دمای اگزوز",
  "measurement.lube_oil_pressure": "فشار روغن روانکاری",
  "conflictType.timestamp": "اختلاف زمان",
  "conflictType.date": "اختلاف تاریخ",
  "conflictType.measurement": "اختلاف اندازه‌گیری",
  "conflictType.value": "اختلاف مقدار",
};

const catalogs: Record<Locale, Record<ChronologyKey, string>> = { en, fa };

export function chronologyT(
  locale: Locale,
  key: ChronologyKey,
  values?: Record<string, string | number>,
): string {
  let text = catalogs[locale][key];
  if (!values) return text;
  for (const [name, value] of Object.entries(values)) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

export function materialityLabel(locale: Locale, value: string): string {
  const key = `materiality.${value}` as ChronologyKey;
  return key in catalogs[locale] ? catalogs[locale][key] : value.replaceAll("_", " ");
}

export function conflictStatusLabel(locale: Locale, value: string): string {
  const key = `status.${value}` as ChronologyKey;
  return key in catalogs[locale] ? catalogs[locale][key] : value.replaceAll("_", " ");
}

export function conflictTypeLabel(locale: Locale, value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("timestamp") || normalized.includes("time")) return chronologyT(locale, "conflictType.timestamp");
  if (normalized.includes("date")) return chronologyT(locale, "conflictType.date");
  if (normalized.includes("measurement")) return chronologyT(locale, "conflictType.measurement");
  if (normalized.includes("value")) return chronologyT(locale, "conflictType.value");
  return value.replaceAll("_", " ");
}
