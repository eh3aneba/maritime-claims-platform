import type { Locale } from "./i18n";

export type AccessibilityCopyKey =
  | "routeLoading"
  | "errorEyebrow"
  | "errorTitle"
  | "errorDescription"
  | "retry";

const copy: Record<Locale, Record<AccessibilityCopyKey, string>> = {
  en: {
    routeLoading: "Loading claims workspace…",
    errorEyebrow: "Workspace error",
    errorTitle: "This view could not be loaded",
    errorDescription:
      "Your claim data has not been changed. Retry the request; if the problem continues, check API health and the deployment logs.",
    retry: "Try again",
  },
  fa: {
    routeLoading: "در حال بارگذاری محیط رسیدگی به خسارت…",
    errorEyebrow: "خطای محیط کار",
    errorTitle: "این صفحه بارگذاری نشد",
    errorDescription:
      "اطلاعات پرونده شما تغییر نکرده است. دوباره تلاش کنید؛ اگر مشکل ادامه داشت، وضعیت API و لاگ‌های استقرار را بررسی کنید.",
    retry: "تلاش دوباره",
  },
};

export function accessibilityT(locale: Locale, key: AccessibilityCopyKey): string {
  return copy[locale][key];
}
