"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { useLocale } from "@/components/locale-provider";
import { claimWorkspaceT } from "@/lib/i18n-claim-workspace";
import { reviewT } from "@/lib/i18n-review-support";

import ClaimOverviewCore from "./overview-core";

export default function ClaimOverviewPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const cw = (key: Parameters<typeof claimWorkspaceT>[1]) => claimWorkspaceT(locale, key);
  const r = (en: string, fa: string) => reviewT(locale, en, fa);

  return (
    <div>
      <div className="mb-4 flex flex-wrap justify-end gap-2">
        <Link href={`/claims/${id}/claim-qa`} className="secondary-button">{cw("overview.quick.claimQa")}</Link>
        <Link href={`/claims/${id}/evidence-search`} className="secondary-button">{cw("overview.quick.evidenceSearch")}</Link>
        <Link href={`/claims/${id}/recovery-timebar`} className="secondary-button">{cw("overview.quick.recovery")}</Link>
        <Link href={`/claims/${id}/recovery-timebar/maturity`} className="secondary-button">{r("Recovery scenarios", "سناریوهای بازیافت")}</Link>
        <Link href={`/claims/${id}/severity-reserve`} className="secondary-button">{cw("overview.quick.severity")}</Link>
      </div>
      <ClaimOverviewCore />
    </div>
  );
}