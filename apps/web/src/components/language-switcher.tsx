"use client";

import { useLocale } from "@/components/locale-provider";

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useLocale();

  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1 text-xs shadow-sm" aria-label={t("common.language")}>
      <button
        type="button"
        onClick={() => setLocale("en")}
        aria-pressed={locale === "en"}
        className={`rounded-md px-2.5 py-1.5 font-semibold transition ${locale === "en" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
      >
        {compact ? "EN" : t("common.english")}
      </button>
      <button
        type="button"
        onClick={() => setLocale("fa")}
        aria-pressed={locale === "fa"}
        className={`rounded-md px-2.5 py-1.5 font-semibold transition ${locale === "fa" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
      >
        {compact ? "FA" : t("common.persian")}
      </button>
    </div>
  );
}
