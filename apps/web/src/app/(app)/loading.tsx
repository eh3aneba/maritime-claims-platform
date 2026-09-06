"use client";

import { useLocale } from "@/components/locale-provider";
import { accessibilityT } from "@/lib/i18n-accessibility";

export default function Loading() {
  const { locale } = useLocale();

  return (
    <div className="space-y-5" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{accessibilityT(locale, "routeLoading")}</span>
      <div className="h-5 w-36 animate-pulse rounded bg-slate-200" aria-hidden="true" />
      <div className="h-10 w-72 animate-pulse rounded bg-slate-200" aria-hidden="true" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
        {Array.from({ length: 4 }).map((_, index) => <div key={index} className="panel h-28 animate-pulse bg-slate-100" />)}
      </div>
      <div className="panel h-72 animate-pulse bg-slate-100" aria-hidden="true" />
    </div>
  );
}
