"use client";

import { useEffect, useRef } from "react";

import { useLocale } from "@/components/locale-provider";
import { accessibilityT } from "@/lib/i18n-accessibility";

export default function ErrorState({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { locale } = useLocale();
  const headingRef = useRef<HTMLHeadingElement | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section
      role="alert"
      aria-labelledby="workspace-error-title"
      aria-describedby="workspace-error-description"
      className="panel mx-auto mt-16 max-w-2xl p-8 text-center"
    >
      <p className="eyebrow">{accessibilityT(locale, "errorEyebrow")}</p>
      <h1
        id="workspace-error-title"
        ref={headingRef}
        tabIndex={-1}
        className="mt-2 text-2xl font-semibold text-slate-950 outline-none"
      >
        {accessibilityT(locale, "errorTitle")}
      </h1>
      <p id="workspace-error-description" className="mt-3 text-sm leading-6 text-slate-500">
        {accessibilityT(locale, "errorDescription")}
      </p>
      <button onClick={reset} className="primary-button mt-6">
        {accessibilityT(locale, "retry")}
      </button>
    </section>
  );
}
