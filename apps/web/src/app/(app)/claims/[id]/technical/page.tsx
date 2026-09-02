"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim, getTechnicalReview } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import { maintenanceLabel, reviewT, severityLabel, technicalStatusLabel } from "@/lib/i18n-review-support";
import type { Locale } from "@/lib/i18n";
import type { Claim, TechnicalEvidenceItem, TechnicalReviewResponse } from "@/lib/types";

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

function EvidenceCard({ item, locale }: { item: unknown; locale: Locale }) {
  if (item === null || item === undefined) return null;
  if (typeof item !== "object" || Array.isArray(item)) return <p className="text-sm text-slate-700" dir="auto">{formatStructuredValue(item)}</p>;
  const record = item as Record<string, unknown>;
  const technical = record as unknown as TechnicalEvidenceItem;
  const sourceQuote = typeof technical.source_quote === "string" ? technical.source_quote : null;
  const value = Object.prototype.hasOwnProperty.call(record, "value") ? record.value : null;
  const fieldPath = typeof record.field_path === "string" ? record.field_path : null;
  const visibleEntries = Object.entries(record).filter(([key]) => ![
    "extraction_id", "document_id", "source_quote", "source_locator_type", "source_locator_value", "source_verified", "field_path", "value",
  ].includes(key));

  return <div className="rounded-lg border border-slate-200 bg-white p-3">
    {fieldPath ? <p className="text-xs font-semibold uppercase tracking-wide text-slate-400" dir="ltr">{humanizeFieldLabel(fieldPath)}</p> : null}
    {value !== null && value !== undefined ? <p className="mt-1 text-sm font-semibold text-slate-800" dir="auto">{formatStructuredValue(value)}</p> : null}
    {visibleEntries.length ? <dl className="mt-1 grid gap-1 text-sm">{visibleEntries.map(([key, nested]) => <div key={key} className="flex flex-wrap gap-1"><dt className="font-medium text-slate-500" dir="ltr">{humanizeFieldLabel(key)}:</dt><dd className="text-slate-700" dir="auto">{formatStructuredValue(nested)}</dd></div>)}</dl> : null}
    {sourceQuote ? <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-xs leading-5 text-slate-500" dir="auto">{sourceQuote}</blockquote> : null}
    {record.source_verified === true ? <p className="mt-2 text-xs font-medium text-emerald-700">{reviewT(locale, "Source verified", "منبع تأیید شده")}</p> : null}
  </div>;
}

function EvidenceList({ items, empty, locale }: { items: unknown[]; empty: string; locale: Locale }) {
  if (!items.length) return <p className="mt-2 text-sm text-slate-500">{empty}</p>;
  return <div className="mt-3 space-y-2">{items.map((item, index) => <EvidenceCard key={index} item={item} locale={locale} />)}</div>;
}

export default function TechnicalReviewPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [review, setReview] = useState<TechnicalReviewResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getClaim(id), getTechnicalReview(id)]).then(([c, next]) => { setClaim(c); setReview(next); })
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Technical review could not be loaded."));
  }, [id]);

  if (!claim && !error) return <div className="py-20 text-center text-sm text-slate-500">{r("Loading technical review…", "در حال بارگذاری بازبینی فنی…")}</div>;
  if (!claim || !review) return <div className="panel p-6 text-sm text-red-700">{error || r("Technical review unavailable.", "بازبینی فنی در دسترس نیست.")}</div>;

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r(`← Back to ${claim.vessel.name}`, `→ بازگشت به ${claim.vessel.name}`)}</Link>
    <div className="mt-5"><p className="eyebrow" dir="ltr">{claim.claim_reference}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Technical review matrix", "ماتریس بازبینی فنی")}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{r("Human-approved maintenance facts and reviewed workshop evidence assembled into investigation topics. The matrix identifies matters for investigation and does not confirm causation.", "واقعیت‌های نگهداری تأییدشده توسط انسان و شواهد بازبینی‌شده کارگاه در موضوعات تحقیق کنار هم قرار می‌گیرند. این ماتریس موارد نیازمند بررسی را نشان می‌دهد و علت خسارت را تأیید نمی‌کند.")}</p></div>

    <section className="panel mt-7 p-6"><h2 className="section-title">{r("Maintenance facts", "واقعیت‌های نگهداری")}</h2><p className="section-subtitle">{r("Only human-approved scalar facts can drive deterministic maintenance rules.", "فقط واقعیت‌های عددی یا تک‌مقداری تأییدشده توسط انسان می‌توانند قواعد قطعی نگهداری را فعال کنند.")}</p><div className="mt-5 grid gap-3 sm:grid-cols-2">{Object.entries(review.maintenance_facts).map(([key, value]) => <div key={key} className="rounded-xl border border-slate-200 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{maintenanceLabel(locale, key, humanizeFieldLabel(key))}</p><p className="mt-2 text-sm font-semibold text-slate-900" dir="auto">{maintenanceValue(locale, key, value)}</p></div>)}{Object.keys(review.maintenance_facts).length === 0 ? <p className="text-sm text-slate-500">{r("No approved maintenance facts yet.", "هنوز واقعیت نگهداری تأییدشده‌ای ثبت نشده است.")}</p> : null}</div></section>

    <section className="mt-6 space-y-4"><div><h2 className="section-title">{r("Investigation matrix", "ماتریس تحقیق")}</h2><p className="section-subtitle">{r("Supporting evidence, counter-evidence, unknowns and recommended follow-up are kept separate.", "شواهد مؤید، شواهد مخالف، موارد نامشخص و پیگیری پیشنهادی جدا از هم نگهداری می‌شوند.")}</p></div>{review.matrix.length ? review.matrix.map((row) => <article key={row.key} className="panel p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">{r("Investigation priority", "اولویت تحقیق")}: {severityLabel(locale, row.severity)} · {technicalStatusLabel(locale, row.status)}</p><h3 className="mt-1 text-lg font-semibold text-slate-950" dir="auto">{row.title}</h3></div></div><p className="mt-3 text-sm leading-6 text-slate-600" dir="auto">{row.explanation}</p><div className="mt-5 grid gap-4 lg:grid-cols-2"><div className="rounded-xl bg-emerald-50 p-4"><p className="text-xs font-bold uppercase tracking-wide text-emerald-700">{r("Evidence for", "شواهد مؤید")}</p><EvidenceList locale={locale} items={row.evidence_for} empty={r("No supporting evidence recorded.", "شواهد مؤیدی ثبت نشده است.")} /></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-600">{r("Evidence against / counter-evidence", "شواهد مخالف / متقابل")}</p><EvidenceList locale={locale} items={row.evidence_against} empty={r("No counter-evidence recorded.", "شواهد مخالفی ثبت نشده است.")} /></div></div><div className="mt-4 grid gap-4 lg:grid-cols-2"><div><p className="text-xs font-bold uppercase tracking-wide text-amber-700">{r("Unknown / missing", "نامشخص / مفقود")}</p><ul className="mt-2 space-y-1 text-sm text-slate-700" dir="auto">{row.unknown_or_missing.length ? row.unknown_or_missing.map((item) => <li key={item}>• {item}</li>) : <li>• {r("No material unknowns recorded.", "مورد نامشخص بااهمیتی ثبت نشده است.")}</li>}</ul></div><div><p className="text-xs font-bold uppercase tracking-wide text-cyan-700">{r("Recommended follow-up", "پیگیری پیشنهادی")}</p><ul className="mt-2 space-y-1 text-sm text-slate-700" dir="auto">{row.recommended_follow_up.length ? row.recommended_follow_up.map((item) => <li key={item}>• {item}</li>) : <li>• {r("No system-generated follow-up recorded.", "پیگیری سیستمی ثبت نشده است.")}</li>}</ul></div></div></article>) : <div className="panel p-8 text-center text-sm text-slate-500">{r("No technical investigation topics yet. Review maintenance/workshop evidence and refresh Rules.", "هنوز موضوع فنی برای تحقیق وجود ندارد. شواهد نگهداری/کارگاه را بازبینی و Rules را به‌روزرسانی کنید.")}</div>}</section>

    <section className="panel mt-6 p-6"><div className="flex items-start justify-between gap-4"><div><h2 className="section-title">{r("Reviewed workshop evidence", "شواهد بازبینی‌شده کارگاه")}</h2><p className="section-subtitle">{r("Counts below are evidence fields; expand each category to inspect the human-reviewed content without internal database IDs.", "اعداد زیر تعداد فیلدهای شاهد هستند؛ هر دسته را باز کنید تا محتوای بازبینی‌شده انسانی را بدون شناسه‌های داخلی پایگاه داده ببینید.")}</p></div></div><div className="mt-4 grid gap-5 lg:grid-cols-3">
      <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{r("Damage findings", "یافته‌های خسارت")}</p><p className="mt-2 text-2xl font-semibold" dir="ltr">{review.workshop_findings.length}</p></summary><div className="mt-4 space-y-2">{review.workshop_findings.map((item, index) => <EvidenceCard key={index} item={item} locale={locale} />)}</div></details>
      <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{r("Repair-option fields", "فیلدهای گزینه تعمیر")}</p><p className="mt-2 text-2xl font-semibold" dir="ltr">{review.workshop_repair_options.length}</p></summary><div className="mt-4 space-y-2">{review.workshop_repair_options.map((item, index) => <EvidenceCard key={index} item={item} locale={locale} />)}</div></details>
      <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{r("Cause opinions", "نظرات درباره علت")}</p><p className="mt-2 text-2xl font-semibold" dir="ltr">{review.workshop_cause_opinions.length}</p></summary><div className="mt-4 space-y-2">{review.workshop_cause_opinions.map((item, index) => <EvidenceCard key={index} item={item} locale={locale} />)}</div></details>
    </div></section>
  </div>;
}
