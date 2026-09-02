"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getFinancialReview, resolveFinancialFlag, updateCostStatus } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { costStatusLabel, reviewT, severityLabel, supportStatusLabel } from "@/lib/i18n-review-support";
import type { Locale } from "@/lib/i18n";
import type { CostReviewStatus, FinancialCostItem, FinancialReviewResponse } from "@/lib/types";

const costStatuses: CostReviewStatus[] = [
  "claimed",
  "under_review",
  "potentially_recoverable",
  "potentially_non_recoverable",
  "accepted",
  "rejected",
  "paid",
];

function sumItems(items: FinancialCostItem[], statuses?: CostReviewStatus[]) {
  const totals: Record<string, number> = {};
  for (const item of items) {
    if (statuses && !statuses.includes(item.review_status)) continue;
    totals[item.currency] = (totals[item.currency] ?? 0) + Number(item.amount);
  }
  return totals;
}

function totalsText(locale: Locale, totals: Record<string, number>) {
  const entries = Object.entries(totals);
  if (!entries.length) return reviewT(locale, "None recorded", "موردی ثبت نشده");
  return entries.map(([currency, amount]) => formatMoney(amount, currency)).join(" · ");
}

export default function FinancialReviewPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [data, setData] = useState<FinancialReviewResponse | null>(null);
  const [error, setError] = useState("");

  const load = () => getFinancialReview(id).then((result) => { setData(result); setError(""); }).catch((e) => setError(e instanceof ApiError ? e.detail : "Financial review could not be loaded."));
  useEffect(() => { load(); }, [id]);

  async function setStatus(itemId: string, status: CostReviewStatus) {
    const reason = window.prompt(r("Reason for status change?", "دلیل تغییر وضعیت چیست؟"));
    if (!reason) return;
    await updateCostStatus(id, itemId, status, reason);
    load();
  }

  async function resolve(idFlag: string) {
    const note = window.prompt(r("Resolution/explanation?", "توضیح یا نحوه حل؟"));
    if (!note) return;
    await resolveFinancialFlag(id, idFlag, "explained", note);
    load();
  }

  const groups = useMemo(() => {
    if (!data) return [];
    const grouped = new Map<string, FinancialCostItem[]>();
    for (const item of data.items) grouped.set(item.document_id, [...(grouped.get(item.document_id) ?? []), item]);
    return Array.from(grouped.entries()).map(([documentId, items]) => ({ documentId, items })).sort((a, b) => {
      const ak = a.items[0]?.document_kind === "invoice" ? 0 : 1;
      const bk = b.items[0]?.document_kind === "invoice" ? 0 : 1;
      return ak - bk;
    });
  }, [data]);

  if (!data) return <div className="panel p-6">{error || r("Loading financial review…", "در حال بارگذاری بازبینی مالی…")}</div>;

  const invoiceTotals = Object.fromEntries(Object.entries(data.totals_by_currency).map(([currency, value]) => [currency, Number(value)]));
  const acceptedTotals = sumItems(data.items.filter((item) => item.document_kind === "invoice"), ["accepted", "paid"]);
  const paidTotals = sumItems(data.items.filter((item) => item.document_kind === "invoice"), ["paid"]);
  const latestReserve = data.reserve_history[0];

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500">{r("← Back to claim", "→ بازگشت به پرونده")}</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-end"><div><p className="eyebrow">{r("Cost control intelligence", "هوشمندی کنترل هزینه")}</p><h1 className="mt-2 text-3xl font-semibold text-slate-950">{r("Financial review", "بازبینی مالی")}</h1><p className="mt-2 text-sm text-slate-500">{r("Human-reviewed commercial evidence, deterministic flags and reserve history. No automatic recoverability or supplier selection.", "شواهد تجاری بازبینی‌شده توسط انسان، پرچم‌های قطعی و تاریخچه ذخیره. هیچ تشخیص خودکار قابلیت بازیافت یا انتخاب تأمین‌کننده انجام نمی‌شود.")}</p></div><Link href={`/claims/${id}/adjustment`} className="primary-button whitespace-nowrap">{r("Open Adjustment Workspace", "باز کردن محیط Adjustment")}</Link></div>
    {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

    <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <div className="panel p-5"><p className="metric-label">{r("Current reserve", "ذخیره فعلی")}</p><p className="metric-value text-xl" dir="ltr">{latestReserve ? formatMoney(latestReserve.amount, latestReserve.currency) : r("None recorded", "موردی ثبت نشده")}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("Actual / invoiced", "واقعی / صورتحساب‌شده")}</p><p className="metric-value text-xl" dir="ltr">{totalsText(locale, invoiceTotals)}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("Accepted invoice cost", "هزینه صورتحساب پذیرفته‌شده")}</p><p className="metric-value text-xl" dir="ltr">{totalsText(locale, acceptedTotals)}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("Paid", "پرداخت‌شده")}</p><p className="metric-value text-xl" dir="ltr">{totalsText(locale, paidTotals)}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("Open review flags", "پرچم‌های باز بازبینی")}</p><p className="metric-value" dir="ltr">{data.flags.filter((flag) => flag.status === "open").length}</p></div>
    </section>

    <section className="panel mt-6 p-6">
      <div className="flex flex-col justify-between gap-2 lg:flex-row lg:items-end"><div><h2 className="section-title">{r("Commercial evidence & cost schedule", "شواهد تجاری و برنامه هزینه")}</h2><p className="section-subtitle">{r("Invoice costs and quotation alternatives are grouped by source document so alternative repair scopes are never presented as cumulative claim exposure.", "هزینه‌های صورتحساب و گزینه‌های قیمت‌گذاری بر اساس سند منبع گروه‌بندی می‌شوند تا دامنه‌های جایگزین تعمیر هرگز به‌عنوان مجموع تعهد خسارت نمایش داده نشوند.")}</p></div></div>
      <div className="mt-5 space-y-5">{groups.map(({ documentId, items }) => {
        const first = items[0];
        const isInvoice = first.document_kind === "invoice";
        const groupTotal = items.reduce((sum, item) => sum + Number(item.amount), 0);
        const quotation = data.quotations.find((q) => q.document_id === documentId);
        const label = isInvoice ? r("Invoice / actual commercial evidence", "صورتحساب / شواهد تجاری واقعی") : r("Quotation alternative", "گزینه قیمت‌گذاری");
        return <div key={documentId} className="rounded-xl border border-slate-200">
          <div className="flex flex-col justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 md:flex-row md:items-center"><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 font-semibold text-slate-900" dir="auto">{first.supplier || (isInvoice ? r("Invoice", "صورتحساب") : r("Quotation", "قیمت‌گذاری"))} <span dir="ltr">{first.document_number || ""}</span></p>{!isInvoice && quotation?.scope_summary ? <p className="mt-1 text-xs text-slate-500" dir="auto">{quotation.scope_summary}</p> : null}</div><div className="text-left md:text-right"><p className="text-xs uppercase tracking-wide text-slate-400">{r("Reviewed line-item total", "جمع اقلام بازبینی‌شده")}</p><p className="font-semibold text-slate-900" dir="ltr">{formatMoney(groupTotal, first.currency)}</p>{!isInvoice && quotation?.total ? <p className="text-xs text-slate-500">{r("Document total", "جمع سند")}: <span dir="ltr">{formatMoney(quotation.total, quotation.currency || first.currency)}</span></p> : null}</div></div>
          <div className="overflow-x-auto"><table className="data-table min-w-[900px]"><thead><tr><th>{r("Description", "شرح")}</th><th>{r("Amount", "مبلغ")}</th><th>{r("Category", "دسته")}</th><th>{r("Evidence type", "نوع شاهد")}</th><th>{r("Status", "وضعیت")}</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td dir="auto">{item.description}</td><td dir="ltr">{formatMoney(item.amount, item.currency)}</td><td dir="auto">{item.category || "—"}</td><td><span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{isInvoice ? r("Actual / invoiced", "واقعی / صورتحساب‌شده") : r("Quoted alternative", "گزینه قیمت‌گذاری")}</span></td><td><select value={item.review_status} onChange={(e) => setStatus(item.id, e.target.value as CostReviewStatus)} className="field py-1 text-xs">{costStatuses.map((value) => <option key={value} value={value}>{costStatusLabel(locale, value)}</option>)}</select></td></tr>)}</tbody></table></div>
        </div>;
      })}</div>
    </section>

    <section className="mt-6 grid gap-6 xl:grid-cols-2">
      <div className="panel p-6"><h2 className="section-title">{r("Financial flags", "پرچم‌های مالی")}</h2><p className="section-subtitle">{r("Flags are review cues only. They do not determine recoverability or select a supplier.", "پرچم‌ها فقط نشانه بازبینی هستند. آن‌ها قابلیت بازیافت را تعیین یا تأمین‌کننده را انتخاب نمی‌کنند.")}</p><div className="mt-4 space-y-3">{data.flags.length ? data.flags.map((flag) => <div key={flag.id} className="rounded-lg border border-slate-200 p-4"><div className="flex justify-between gap-3"><div><p className="font-semibold text-slate-900" dir="auto">{flag.title}</p><p className="mt-1 text-xs uppercase text-slate-400">{r("Review severity", "شدت بازبینی")}: {severityLabel(locale, flag.severity)} · <span dir="ltr">{flag.flag_type.replaceAll("_", " ")}</span></p></div><span className="text-xs font-semibold">{supportStatusLabel(locale, flag.status)}</span></div><p className="mt-3 text-sm text-slate-600" dir="auto">{flag.explanation}</p>{flag.status === "open" ? <button onClick={() => resolve(flag.id)} className="secondary-button mt-3">{r("Explain / resolve", "توضیح / حل")}</button> : flag.resolution_note ? <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600" dir="auto"><span className="font-semibold">{r("Review note", "یادداشت بازبینی")}:</span> {flag.resolution_note}</p> : null}</div>) : <p className="text-sm text-slate-500">{r("No current flags.", "در حال حاضر پرچمی وجود ندارد.")}</p>}</div></div>
      <div className="panel p-6"><h2 className="section-title">{r("Quotation alternatives", "گزینه‌های قیمت‌گذاری")}</h2><p className="section-subtitle">{r("Different scopes are displayed as alternatives and are not added together as claim exposure.", "دامنه‌های متفاوت به‌صورت گزینه‌های جایگزین نمایش داده می‌شوند و به‌عنوان مجموع تعهد خسارت با هم جمع نمی‌شوند.")}</p><div className="mt-4 space-y-3">{data.quotations.map((quote) => <div key={quote.document_id} className="rounded-lg border border-slate-200 p-4"><p className="font-semibold" dir="auto">{quote.supplier || r("Quotation", "قیمت‌گذاری")} <span dir="ltr">{quote.quotation_number || ""}</span></p><p className="mt-1 text-lg font-semibold text-slate-900" dir="ltr">{quote.total ? formatMoney(quote.total, quote.currency || "USD") : r("Total not established", "جمع مشخص نشده")}</p><p className="mt-2 text-sm text-slate-600" dir="auto">{quote.scope_summary || r("Scope not yet approved.", "دامنه هنوز تأیید نشده است.")}</p><p className="mt-2 text-xs text-slate-400">{r("Lead time", "زمان تأمین")}: <span dir="auto">{quote.lead_time || "—"}</span> · {r("Repair duration", "مدت تعمیر")}: <span dir="auto">{quote.repair_duration || "—"}</span></p></div>)}</div></div>
    </section>

    <section className="panel mt-6 p-6"><h2 className="section-title">{r("Reserve history", "تاریخچه ذخیره")}</h2><div className="mt-4 space-y-2">{data.reserve_history.length ? data.reserve_history.map((row) => <div key={row.id} className="flex flex-col justify-between gap-2 border-b border-slate-100 py-3 sm:flex-row"><div><p className="font-medium" dir="ltr">{formatMoney(row.amount, row.currency)}</p><p className="text-xs text-slate-500" dir="auto">{row.reason}</p></div><span className="text-xs text-slate-400" dir="ltr">{formatDateTime(row.created_at)}</span></div>) : <p className="text-sm text-slate-500">{r("No reserve history recorded.", "تاریخچه ذخیره‌ای ثبت نشده است.")}</p>}</div></section>
  </div>;
}
