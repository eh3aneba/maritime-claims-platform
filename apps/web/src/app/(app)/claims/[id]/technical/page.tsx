"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { TechnicalInvestigationReview } from "@/components/technical-investigation-review";
import { ApiError, getClaim } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import { maintenanceLabel, reviewT } from "@/lib/i18n-review-support";
import type { Locale } from "@/lib/i18n";
import {
  getMatureTechnicalReview,
  type MatureTechnicalReviewResponse,
  type TechnicalEvidenceItem,
} from "@/lib/technical-maturity-api";
import type { Claim } from "@/lib/types";

function maintenanceValue(locale: Locale, key: string, value: unknown) {
  if (key === "maintenance.interval_extension_details" && String(value).toLowerCase().includes("no approved extension")) {
    return reviewT(
      locale,
      "No maker-approved interval extension evidenced in the reviewed claim file",
      "در پرونده بازبینی‌شده، شواهدی از تمدید فاصله سرویس با تأیید سازنده وجود ندارد",
    );
  }
  return formatStructuredValue(value);
}

function EvidenceCard({
  claimId,
  item,
  locale,
}: {
  claimId: string;
  item: TechnicalEvidenceItem;
  locale: Locale;
}) {
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const sourceHref = item.document_id || item.extraction_id
    ? `/claims/${claimId}/evidence-matrix?document_id=${encodeURIComponent(item.document_id ?? "")}&extraction_id=${encodeURIComponent(item.extraction_id ?? "")}`
    : `/claims/${claimId}/evidence-matrix`;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400" dir="ltr">
            {humanizeFieldLabel(item.field_path)}
          </p>
          <p className="mt-1 text-sm font-semibold text-slate-800" dir="auto">{formatStructuredValue(item.value)}</p>
        </div>
        <Link className="text-xs font-semibold text-cyan-700 hover:text-cyan-900" href={sourceHref}>
          {r("Open source context", "باز کردن زمینه منبع")}
        </Link>
      </div>
      {item.source_locator_value ? (
        <p className="mt-2 text-xs text-slate-500">
          <span className="font-semibold">{r("Source locator", "نشانی منبع")}:</span>{" "}
          <span dir="ltr">{item.source_locator_value}</span>
          {item.source_locator_type ? <span dir="ltr"> ({item.source_locator_type})</span> : null}
        </p>
      ) : null}
      {item.source_quote ? (
        <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-xs leading-5 text-slate-500" dir="auto">
          {item.source_quote}
        </blockquote>
      ) : null}
      {item.source_verified === true ? (
        <p className="mt-2 text-xs font-medium text-emerald-700">{r("Source verified", "منبع تأیید شده")}</p>
      ) : null}
    </div>
  );
}

export default function TechnicalReviewPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [review, setReview] = useState<MatureTechnicalReviewResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const reloadReview = useCallback(async () => {
    setError("");
    try {
      setReview(await getMatureTechnicalReview(id));
    } catch (nextError) {
      setError(
        nextError instanceof ApiError
          ? nextError.detail
          : reviewT(locale, "Technical review could not be loaded.", "بازبینی فنی قابل بارگذاری نیست."),
      );
      throw nextError;
    }
  }, [id, locale]);

  const loadPage = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextClaim, nextReview] = await Promise.all([getClaim(id), getMatureTechnicalReview(id)]);
      setClaim(nextClaim);
      setReview(nextReview);
    } catch (nextError) {
      setError(
        nextError instanceof ApiError
          ? nextError.detail
          : reviewT(locale, "Technical review could not be loaded.", "بازبینی فنی قابل بارگذاری نیست."),
      );
    } finally {
      setLoading(false);
    }
  }, [id, locale]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

  if (loading && !claim) {
    return <div className="py-20 text-center text-sm text-slate-500">{r("Loading technical review…", "در حال بارگذاری بازبینی فنی…")}</div>;
  }

  if (!claim || !review) {
    return (
      <div className="panel p-6 text-sm text-red-700" role="alert">
        <p dir="auto">{error || r("Technical review unavailable.", "بازبینی فنی در دسترس نیست.")}</p>
        <button className="secondary-button mt-3" onClick={() => void loadPage()}>
          {r("Retry technical review", "تلاش دوباره برای بازبینی فنی")}
        </button>
      </div>
    );
  }

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">
        {r(`← Back to ${claim.vessel.name}`, `→ بازگشت به ${claim.vessel.name}`)}
      </Link>

      <div className="mt-5">
        <p className="eyebrow" dir="ltr">{claim.claim_reference}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Technical review matrix", "ماتریس بازبینی فنی")}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          {r(
            "Human-reviewed maintenance facts and source evidence are assembled into investigation topics. Human dispositions are append-only review decisions and never an autonomous causation, coverage or liability conclusion.",
            "واقعیت‌های نگهداری و شواهد منبع که توسط انسان بازبینی شده‌اند در موضوعات تحقیق کنار هم قرار می‌گیرند. تصمیم‌های انسانی به‌صورت افزایشی در تاریخچه ثبت می‌شوند و هرگز نتیجه‌گیری خودکار درباره علت، پوشش یا مسئولیت نیستند.",
          )}
        </p>
      </div>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700" role="alert">
          <span dir="auto">{error}</span>{" "}
          <button className="font-semibold underline" onClick={() => void reloadReview()}>{r("Retry", "تلاش دوباره")}</button>
        </div>
      ) : null}

      <section className="panel mt-7 p-6">
        <h2 className="section-title">{r("Maintenance facts", "واقعیت‌های نگهداری")}</h2>
        <p className="section-subtitle">
          {r(
            "Only human-approved scalar facts can drive deterministic maintenance rules.",
            "فقط واقعیت‌های عددی یا تک‌مقداری تأییدشده توسط انسان می‌توانند قواعد قطعی نگهداری را فعال کنند.",
          )}
        </p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {Object.entries(review.maintenance_facts).map(([key, value]) => (
            <div key={key} className="rounded-xl border border-slate-200 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{maintenanceLabel(locale, key, humanizeFieldLabel(key))}</p>
              <p className="mt-2 text-sm font-semibold text-slate-900" dir="auto">{maintenanceValue(locale, key, value)}</p>
            </div>
          ))}
          {Object.keys(review.maintenance_facts).length === 0 ? (
            <p className="text-sm text-slate-500">{r("No approved maintenance facts yet.", "هنوز واقعیت نگهداری تأییدشده‌ای ثبت نشده است.")}</p>
          ) : null}
        </div>
      </section>

      <section className="mt-6 space-y-4">
        <div>
          <h2 className="section-title">{r("Controlled investigation topics", "موضوعات کنترل‌شده تحقیق")}</h2>
          <p className="section-subtitle">
            {r(
              "Supporting evidence, counter-evidence, unknowns, follow-up and human decision lineage stay together. If evidence changes, prior decisions are marked stale and require explicit re-review.",
              "شواهد مؤید، شواهد مخالف، موارد نامشخص، پیگیری و تاریخچه تصمیم انسانی در کنار هم باقی می‌مانند. اگر شواهد تغییر کند، تصمیم قبلی قدیمی علامت‌گذاری می‌شود و بازبینی مجدد صریح لازم است.",
            )}
          </p>
        </div>

        {review.matrix.length ? review.matrix.map((row) => (
          <TechnicalInvestigationReview
            claimId={id}
            key={row.key}
            locale={locale}
            onReload={reloadReview}
            row={row}
          />
        )) : (
          <div className="panel p-8 text-center text-sm text-slate-500">
            {r(
              "No technical investigation topics yet. Review maintenance/workshop evidence and refresh Rules.",
              "هنوز موضوع فنی برای تحقیق وجود ندارد. شواهد نگهداری/کارگاه را بازبینی و Rules را به‌روزرسانی کنید.",
            )}
          </div>
        )}
      </section>

      <section className="panel mt-6 p-6">
        <div>
          <h2 className="section-title">{r("Reviewed workshop evidence", "شواهد بازبینی‌شده کارگاه")}</h2>
          <p className="section-subtitle">
            {r(
              "Expand each category to inspect the human-reviewed source content. Cause opinions remain source opinions even when a handler records an investigation disposition.",
              "هر دسته را باز کنید تا محتوای منبع بازبینی‌شده انسانی را ببینید. نظرهای مربوط به علت، حتی پس از ثبت تصمیم تحقیقاتی توسط کارشناس، همچنان نظر منبع باقی می‌مانند.",
            )}
          </p>
        </div>
        <div className="mt-4 grid gap-5 lg:grid-cols-3">
          <details className="rounded-xl border border-slate-200 p-4">
            <summary className="cursor-pointer">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{r("Damage findings", "یافته‌های خسارت")}</p>
              <p className="mt-2 text-2xl font-semibold" dir="ltr">{review.workshop_findings.length}</p>
            </summary>
            <div className="mt-4 space-y-2">
              {review.workshop_findings.map((item, index) => <EvidenceCard claimId={id} item={item} key={index} locale={locale} />)}
            </div>
          </details>
          <details className="rounded-xl border border-slate-200 p-4">
            <summary className="cursor-pointer">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{r("Repair-option fields", "فیلدهای گزینه تعمیر")}</p>
              <p className="mt-2 text-2xl font-semibold" dir="ltr">{review.workshop_repair_options.length}</p>
            </summary>
            <div className="mt-4 space-y-2">
              {review.workshop_repair_options.map((item, index) => <EvidenceCard claimId={id} item={item} key={index} locale={locale} />)}
            </div>
          </details>
          <details className="rounded-xl border border-slate-200 p-4">
            <summary className="cursor-pointer">
              <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{r("Cause opinions", "نظرات درباره علت")}</p>
              <p className="mt-2 text-2xl font-semibold" dir="ltr">{review.workshop_cause_opinions.length}</p>
            </summary>
            <div className="mt-4 space-y-2">
              {review.workshop_cause_opinions.map((item, index) => <EvidenceCard claimId={id} item={item} key={index} locale={locale} />)}
            </div>
          </details>
        </div>
      </section>
    </div>
  );
}
