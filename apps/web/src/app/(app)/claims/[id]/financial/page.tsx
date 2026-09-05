"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, resolveFinancialFlag } from "@/lib/api";
import {
  getMatureFinancialReview,
  recordCostReviewDecision,
  type CostDecisionState,
  type CostReviewStatus,
  type MatureFinancialCostItem,
  type MatureFinancialReviewResponse,
} from "@/lib/financial-maturity-api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { costStatusLabel, reviewT, severityLabel, supportStatusLabel } from "@/lib/i18n-review-support";
import type { Locale } from "@/lib/i18n";

const costStatuses: CostReviewStatus[] = [
  "claimed",
  "under_review",
  "potentially_recoverable",
  "potentially_non_recoverable",
  "accepted",
  "rejected",
  "paid",
];

const decisionStateClasses: Record<CostDecisionState, string> = {
  none: "bg-slate-100 text-slate-600",
  current: "bg-emerald-50 text-emerald-700",
  stale: "bg-amber-50 text-amber-800",
};

function sumItems(items: MatureFinancialCostItem[], statuses?: CostReviewStatus[]) {
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

function shortHash(value: string | null) {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function decisionStateLabel(locale: Locale, state: CostDecisionState) {
  if (state === "current") return reviewT(locale, "Current human review", "بازبینی انسانی فعلی");
  if (state === "stale") return reviewT(locale, "Prior review is stale", "بازبینی قبلی قدیمی شده است");
  return reviewT(locale, "No human review", "بازبینی انسانی ثبت نشده است");
}

export default function FinancialReviewPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [data, setData] = useState<MatureFinancialReviewResponse | null>(null);
  const [error, setError] = useState("");
  const [busyItem, setBusyItem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getMatureFinancialReview(id));
      setError("");
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.detail
          : r("Financial review could not be loaded.", "بازبینی مالی قابل بارگذاری نیست."),
      );
    }
  }, [id, locale]);

  useEffect(() => {
    void load();
  }, [load]);

  async function setStatus(item: MatureFinancialCostItem, status: CostReviewStatus) {
    const reason = window.prompt(r("Reason for this human cost-review disposition?", "دلیل این تصمیم انسانی درباره هزینه چیست؟"));
    if (!reason?.trim()) return;

    const hasPriorDecision = Boolean(item.latest_review_decision);
    if (hasPriorDecision) {
      const confirmed = window.confirm(
        item.decision_state === "stale"
          ? r(
              "The prior disposition is stale because financial evidence changed. Re-review this current evidence and record a new append-only disposition?",
              "به دلیل تغییر شواهد مالی، تصمیم قبلی قدیمی شده است. آیا شواهد فعلی را دوباره بازبینی و یک تصمیم جدید و غیرقابل‌حذف ثبت می‌کنید؟",
            )
          : r(
              "A prior human disposition exists for this evidence state. Record a deliberate re-review as a new history entry?",
              "برای این وضعیت شواهد، تصمیم انسانی قبلی وجود دارد. آیا بازبینی مجدد را به‌عنوان یک رکورد جدید در تاریخچه ثبت می‌کنید؟",
            ),
      );
      if (!confirmed) return;
    }

    setBusyItem(item.id);
    setError("");
    try {
      await recordCostReviewDecision(id, item.id, {
        status,
        reason: reason.trim(),
        expected_state_fingerprint: item.state_fingerprint,
        expected_state_version: item.state_version,
        confirm_re_review: hasPriorDecision,
      });
      await load();
    } catch (reviewError) {
      if (reviewError instanceof ApiError && reviewError.status === 409) {
        setError(r(
          "Financial evidence changed while you were reviewing it. The stale write was rejected. Review the refreshed current item before submitting again.",
          "شواهد مالی هنگام بازبینی تغییر کرده است. ثبت تصمیم قدیمی رد شد. پیش از ارسال دوباره، قلم فعلیِ تازه‌شده را بازبینی کنید.",
        ));
        await load();
      } else if (reviewError instanceof ApiError && reviewError.status === 403) {
        setError(r(
          "You do not have permission to record this financial disposition.",
          "شما مجوز ثبت این تصمیم مالی را ندارید.",
        ));
      } else {
        setError(
          reviewError instanceof ApiError
            ? reviewError.detail
            : r("Cost-review disposition could not be recorded.", "تصمیم بازبینی هزینه ثبت نشد."),
        );
      }
    } finally {
      setBusyItem(null);
    }
  }

  async function resolve(flagId: string) {
    const note = window.prompt(r("Resolution/explanation?", "توضیح یا نحوه حل؟"));
    if (!note?.trim()) return;
    try {
      await resolveFinancialFlag(id, flagId, "explained", note.trim());
      await load();
    } catch (flagError) {
      setError(
        flagError instanceof ApiError
          ? flagError.detail
          : r("Financial flag could not be updated.", "پرچم مالی قابل به‌روزرسانی نیست."),
      );
    }
  }

  const groups = useMemo(() => {
    if (!data) return [];
    const grouped = new Map<string, MatureFinancialCostItem[]>();
    for (const item of data.items) {
      grouped.set(item.document_id, [...(grouped.get(item.document_id) ?? []), item]);
    }
    return Array.from(grouped.entries())
      .map(([documentId, items]) => ({ documentId, items }))
      .sort((a, b) => {
        const aKind = a.items[0]?.document_kind === "invoice" ? 0 : 1;
        const bKind = b.items[0]?.document_kind === "invoice" ? 0 : 1;
        return aKind - bKind;
      });
  }, [data]);

  if (!data) {
    return (
      <div className="panel p-6">
        {error || r("Loading financial review…", "در حال بارگذاری بازبینی مالی…")}
      </div>
    );
  }

  const invoiceTotals = Object.fromEntries(
    Object.entries(data.totals_by_currency).map(([currency, value]) => [currency, Number(value)]),
  );
  const invoiceItems = data.items.filter((item) => item.document_kind === "invoice");
  const acceptedTotals = sumItems(invoiceItems, ["accepted", "paid"]);
  const paidTotals = sumItems(invoiceItems, ["paid"]);
  const latestReserve = data.reserve_history[0];

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500">
        {r("← Back to claim", "→ بازگشت به پرونده")}
      </Link>

      <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="eyebrow">{r("Cost control intelligence", "هوشمندی کنترل هزینه")}</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">{r("Financial review", "بازبینی مالی")}</h1>
          <p className="mt-2 max-w-4xl text-sm text-slate-500">
            {r(
              "Current usable commercial evidence with state-bound human cost review. Financial flags are review cues only; no automatic recoverability, reserve, settlement, payment or supplier decision is made.",
              "شواهد تجاری قابل‌استفاده فعلی همراه با بازبینی انسانی هزینه که به وضعیت دقیق شواهد متصل است. پرچم‌های مالی فقط نشانه بازبینی هستند و هیچ تصمیم خودکار درباره قابلیت بازیافت، ذخیره، تسویه، پرداخت یا انتخاب تأمین‌کننده انجام نمی‌شود.",
            )}
          </p>
        </div>
        <Link href={`/claims/${id}/adjustment`} className="primary-button whitespace-nowrap">
          {r("Open Adjustment Workspace", "باز کردن محیط Adjustment")}
        </Link>
      </div>

      {error ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      ) : null}

      <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <div className="panel p-5">
          <p className="metric-label">{r("Current reserve", "ذخیره فعلی")}</p>
          <p className="metric-value text-xl" dir="ltr">
            {latestReserve ? formatMoney(latestReserve.amount, latestReserve.currency) : r("None recorded", "موردی ثبت نشده")}
          </p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Actual / invoiced", "واقعی / صورتحساب‌شده")}</p>
          <p className="metric-value text-xl" dir="ltr">{totalsText(locale, invoiceTotals)}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Accepted invoice cost", "هزینه صورتحساب پذیرفته‌شده")}</p>
          <p className="metric-value text-xl" dir="ltr">{totalsText(locale, acceptedTotals)}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Paid status", "وضعیت پرداخت‌شده")}</p>
          <p className="metric-value text-xl" dir="ltr">{totalsText(locale, paidTotals)}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Stale reviews", "بازبینی‌های قدیمی")}</p>
          <p className="metric-value" dir="ltr">{data.summary.stale_decision_count}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Unreviewed items", "اقلام بازبینی‌نشده")}</p>
          <p className="metric-value" dir="ltr">{data.summary.unreviewed_item_count}</p>
        </div>
      </section>

      <section className="panel mt-6 p-6">
        <h2 className="section-title">{r("Commercial evidence & cost schedule", "شواهد تجاری و برنامه هزینه")}</h2>
        <p className="section-subtitle">
          {r(
            "Invoice costs and quotation alternatives are grouped by current source document. A prior human disposition becomes stale when its underlying evidence changes and is never silently transferred.",
            "هزینه‌های صورتحساب و گزینه‌های قیمت‌گذاری بر اساس سند منبع فعلی گروه‌بندی می‌شوند. اگر شواهد زیربنایی تغییر کند، تصمیم انسانی قبلی قدیمی محسوب می‌شود و هرگز به‌طور خاموش منتقل نمی‌شود.",
          )}
        </p>

        <div className="mt-5 space-y-5">
          {groups.length ? groups.map(({ documentId, items }) => {
            const first = items[0];
            const isInvoice = first.document_kind === "invoice";
            const groupTotal = items.reduce((sum, item) => sum + Number(item.amount), 0);
            const quotation = data.quotations.find((row) => row.document_id === documentId);
            const label = isInvoice
              ? r("Invoice / actual commercial evidence", "صورتحساب / شواهد تجاری واقعی")
              : r("Quotation alternative", "گزینه قیمت‌گذاری");

            return (
              <div key={documentId} className="rounded-xl border border-slate-200">
                <div className="flex flex-col justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 md:flex-row md:items-center">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p>
                    <p className="mt-1 font-semibold text-slate-900" dir="auto">
                      {first.supplier || (isInvoice ? r("Invoice", "صورتحساب") : r("Quotation", "قیمت‌گذاری"))}{" "}
                      <span dir="ltr">{first.document_number || ""}</span>
                    </p>
                    <p className="mt-1 text-xs text-slate-500" dir="ltr">
                      {r("Source version", "نسخه منبع")}: v{first.document_version} · {first.source_state.replaceAll("_", " ")}
                    </p>
                    {!isInvoice && quotation?.scope_summary ? (
                      <p className="mt-1 text-xs text-slate-500" dir="auto">{quotation.scope_summary}</p>
                    ) : null}
                  </div>
                  <div className="text-left md:text-right">
                    <p className="text-xs uppercase tracking-wide text-slate-400">{r("Reviewed line-item total", "جمع اقلام بازبینی‌شده")}</p>
                    <p className="font-semibold text-slate-900" dir="ltr">{formatMoney(groupTotal, first.currency)}</p>
                    {!isInvoice && quotation?.total ? (
                      <p className="text-xs text-slate-500">
                        {r("Document total", "جمع سند")}: <span dir="ltr">{formatMoney(quotation.total, quotation.currency || first.currency)}</span>
                      </p>
                    ) : null}
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="data-table min-w-[1180px]">
                    <thead>
                      <tr>
                        <th>{r("Description", "شرح")}</th>
                        <th>{r("Amount", "مبلغ")}</th>
                        <th>{r("Category", "دسته")}</th>
                        <th>{r("Evidence type", "نوع شاهد")}</th>
                        <th>{r("Review state", "وضعیت بازبینی")}</th>
                        <th>{r("Human status", "وضعیت انسانی")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item) => (
                        <tr key={item.id} data-testid={`financial-cost-item-${item.item_key}`}>
                          <td className="max-w-[360px]" dir="auto">
                            <p>{item.description}</p>
                            {item.latest_review_decision ? (
                              <details className="mt-2 text-xs text-slate-500">
                                <summary className="cursor-pointer font-semibold">
                                  {r("Review history", "تاریخچه بازبینی")} ({item.review_history.length})
                                </summary>
                                <div className="mt-2 space-y-2">
                                  {[...item.review_history].reverse().map((decision) => (
                                    <div key={decision.id} className="rounded bg-slate-50 p-2">
                                      <p>
                                        #{decision.decision_number} · {costStatusLabel(locale, decision.status)} · {formatDateTime(decision.reviewed_at)}
                                      </p>
                                      <p className="mt-1" dir="auto">{decision.reason}</p>
                                      <p className="mt-1" dir="ltr">hash {shortHash(decision.decision_hash)}</p>
                                    </div>
                                  ))}
                                </div>
                              </details>
                            ) : null}
                          </td>
                          <td dir="ltr">{formatMoney(item.amount, item.currency)}</td>
                          <td dir="auto">{item.category || "—"}</td>
                          <td>
                            <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
                              {isInvoice ? r("Actual / invoiced", "واقعی / صورتحساب‌شده") : r("Quoted alternative", "گزینه قیمت‌گذاری")}
                            </span>
                          </td>
                          <td>
                            <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${decisionStateClasses[item.decision_state]}`}>
                              {decisionStateLabel(locale, item.decision_state)}
                            </span>
                            <p className="mt-1 text-[10px] text-slate-400" dir="ltr">
                              v{item.state_version} · {shortHash(item.state_fingerprint)}
                            </p>
                            {item.decision_state === "stale" ? (
                              <p className="mt-1 max-w-[220px] text-xs text-amber-700" dir="auto">
                                {r(
                                  "Underlying financial evidence changed. Prior status is not applied to this state.",
                                  "شواهد مالی زیربنایی تغییر کرده است و وضعیت قبلی به این وضعیت اعمال نمی‌شود.",
                                )}
                              </p>
                            ) : null}
                          </td>
                          <td>
                            <select
                              value={item.review_status}
                              disabled={busyItem === item.id}
                              onChange={(event) => void setStatus(item, event.target.value as CostReviewStatus)}
                              className="field py-1 text-xs"
                              aria-label={r("Human cost-review status", "وضعیت بازبینی انسانی هزینه")}
                            >
                              {costStatuses.map((value) => (
                                <option key={value} value={value}>{costStatusLabel(locale, value)}</option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          }) : (
            <p className="text-sm text-slate-500">
              {r("No current usable invoice or quotation line items are available.", "هیچ قلم صورتحساب یا قیمت‌گذاری قابل‌استفاده فعلی در دسترس نیست.")}
            </p>
          )}
        </div>
      </section>

      {data.historical_reviews.length ? (
        <section className="panel mt-6 p-6">
          <h2 className="section-title">{r("Historical stale cost reviews", "بازبینی‌های قدیمی تاریخی هزینه")}</h2>
          <p className="section-subtitle">
            {r(
              "These human dispositions are retained for audit, but their source evidence is no longer current/usable. They do not apply to replacement evidence automatically.",
              "این تصمیم‌های انسانی برای ممیزی حفظ شده‌اند، اما شواهد منبع آن‌ها دیگر فعلی یا قابل‌استفاده نیست. این تصمیم‌ها به‌طور خودکار به شواهد جایگزین اعمال نمی‌شوند.",
            )}
          </p>
          <div className="mt-4 space-y-3">
            {data.historical_reviews.map((row) => (
              <div key={row.item_key} className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-amber-950" dir="auto">
                      {String(row.latest_review_decision.item_snapshot.description ?? r("Historical cost item", "قلم هزینه تاریخی"))}
                    </p>
                    <p className="mt-1 text-sm text-amber-800" dir="auto">{row.message}</p>
                  </div>
                  <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                    {r("Stale / source unavailable", "قدیمی / منبع در دسترس نیست")}
                  </span>
                </div>
                <p className="mt-3 text-xs text-amber-800" dir="auto">
                  {r("Last human status", "آخرین وضعیت انسانی")}: {costStatusLabel(locale, row.latest_review_decision.status)} · {row.latest_review_decision.reason}
                </p>
                <p className="mt-1 text-[11px] text-amber-700" dir="ltr">
                  decision #{row.latest_review_decision.decision_number} · {shortHash(row.latest_review_decision.decision_hash)}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="mt-6 grid gap-6 xl:grid-cols-2">
        <div className="panel p-6">
          <h2 className="section-title">{r("Financial flags", "پرچم‌های مالی")}</h2>
          <p className="section-subtitle">
            {r(
              "Flags are deterministic review cues from current usable evidence only. They do not determine recoverability or select a supplier.",
              "پرچم‌ها فقط نشانه‌های قطعی بازبینی از شواهد قابل‌استفاده فعلی هستند و قابلیت بازیافت را تعیین یا تأمین‌کننده را انتخاب نمی‌کنند.",
            )}
          </p>
          <div className="mt-4 space-y-3">
            {data.flags.length ? data.flags.map((flag) => (
              <div key={flag.id} className="rounded-lg border border-slate-200 p-4">
                <div className="flex justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900" dir="auto">{flag.title}</p>
                    <p className="mt-1 text-xs uppercase text-slate-400">
                      {r("Review severity", "شدت بازبینی")}: {severityLabel(locale, flag.severity)} · <span dir="ltr">{flag.flag_type.replaceAll("_", " ")}</span>
                    </p>
                  </div>
                  <span className="text-xs font-semibold">{supportStatusLabel(locale, flag.status)}</span>
                </div>
                <p className="mt-3 text-sm text-slate-600" dir="auto">{flag.explanation}</p>
                {flag.status === "open" ? (
                  <button onClick={() => void resolve(flag.id)} className="secondary-button mt-3">
                    {r("Explain / resolve", "توضیح / حل")}
                  </button>
                ) : flag.resolution_note ? (
                  <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600" dir="auto">
                    <span className="font-semibold">{r("Review note", "یادداشت بازبینی")}:</span> {flag.resolution_note}
                  </p>
                ) : null}
              </div>
            )) : (
              <p className="text-sm text-slate-500">{r("No current flags.", "در حال حاضر پرچمی وجود ندارد.")}</p>
            )}
          </div>
        </div>

        <div className="panel p-6">
          <h2 className="section-title">{r("Quotation alternatives", "گزینه‌های قیمت‌گذاری")}</h2>
          <p className="section-subtitle">
            {r(
              "Different scopes remain alternatives and are not added together as claim exposure.",
              "دامنه‌های متفاوت به‌صورت گزینه‌های جایگزین باقی می‌مانند و به‌عنوان مجموع تعهد خسارت با هم جمع نمی‌شوند.",
            )}
          </p>
          <div className="mt-4 space-y-3">
            {data.quotations.length ? data.quotations.map((quote) => (
              <div key={quote.document_id} className="rounded-lg border border-slate-200 p-4">
                <p className="font-semibold" dir="auto">
                  {quote.supplier || r("Quotation", "قیمت‌گذاری")} <span dir="ltr">{quote.quotation_number || ""}</span>
                </p>
                <p className="mt-1 text-xs text-slate-400">{r("Source version", "نسخه منبع")}: v{quote.document_version}</p>
                <p className="mt-1 text-lg font-semibold text-slate-900" dir="ltr">
                  {quote.total ? formatMoney(quote.total, quote.currency || "USD") : r("Total not established", "جمع مشخص نشده")}
                </p>
                <p className="mt-2 text-sm text-slate-600" dir="auto">
                  {quote.scope_summary || r("Scope not yet approved.", "دامنه هنوز تأیید نشده است.")}
                </p>
                <p className="mt-2 text-xs text-slate-400">
                  {r("Lead time", "زمان تأمین")}: <span dir="auto">{quote.lead_time || "—"}</span> · {r("Repair duration", "مدت تعمیر")}: <span dir="auto">{quote.repair_duration || "—"}</span>
                </p>
              </div>
            )) : (
              <p className="text-sm text-slate-500">{r("No current quotation alternatives.", "گزینه قیمت‌گذاری فعلی وجود ندارد.")}</p>
            )}
          </div>
        </div>
      </section>

      <section className="panel mt-6 p-6">
        <h2 className="section-title">{r("Reserve history", "تاریخچه ذخیره")}</h2>
        <p className="section-subtitle">
          {r(
            "This is the existing authoritative reserve history. Phase 13.6A does not create or change reserve entries; reserve-range support remains advisory.",
            "این بخش تاریخچه ذخیره معتبر موجود است. فاز 13.6A هیچ ذخیره‌ای ایجاد یا تغییر نمی‌دهد و پشتیبانی بازه ذخیره همچنان مشورتی است.",
          )}
        </p>
        <div className="mt-4 space-y-2">
          {data.reserve_history.length ? data.reserve_history.map((row) => (
            <div key={row.id} className="flex flex-col justify-between gap-2 border-b border-slate-100 py-3 md:flex-row md:items-center">
              <div>
                <p className="font-semibold text-slate-900" dir="ltr">{formatMoney(row.amount, row.currency)}</p>
                <p className="mt-1 text-sm text-slate-600" dir="auto">{row.reason}</p>
              </div>
              <p className="text-xs text-slate-400" dir="ltr">{formatDateTime(row.created_at)}</p>
            </div>
          )) : (
            <p className="text-sm text-slate-500">{r("No reserve history recorded.", "تاریخچه ذخیره‌ای ثبت نشده است.")}</p>
          )}
        </div>
      </section>
    </div>
  );
}
