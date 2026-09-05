"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import {
  createMatureAdjustment,
  listMatureAdjustments,
  rebaseMatureAdjustment,
  reviewMatureAdjustment,
  submitMatureAdjustment,
  updateMatureAdjustment,
  updateMatureAdjustmentLine,
  type AdjustmentBasis,
  type AdjustmentSourceState,
  type AdjustmentTreatment,
  type LineFinancialControls,
  type MatureAdjustmentLine,
  type MatureAdjustmentStatement,
  type SourceGroundedControl,
} from "@/lib/adjustment-maturity-api";
import { ApiError, getClaim, getCurrentUser } from "@/lib/api";
import { getMatureFinancialReview, type MatureFinancialReviewResponse } from "@/lib/financial-maturity-api";
import { formatMoney } from "@/lib/format";
import type { Locale } from "@/lib/i18n";
import { reviewT } from "@/lib/i18n-review-support";
import type { Claim, CurrentUser } from "@/lib/types";

const treatments: AdjustmentTreatment[] = ["pending", "included", "excluded", "apportioned", "credit"];
const bases: AdjustmentBasis[] = ["unallocated", "particular_average", "general_average", "sue_and_labour", "rdc", "other", "not_applicable"];
const controlKinds = ["tax", "depreciation", "betterment", "allocation"] as const;
type ControlKind = (typeof controlKinds)[number];

const statusTone: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  under_review: "bg-amber-50 text-amber-800",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
};

const sourceTone: Record<AdjustmentSourceState, string> = {
  current: "border-emerald-200 bg-emerald-50 text-emerald-900",
  stale: "border-amber-300 bg-amber-50 text-amber-950",
  legacy_unbound: "border-orange-300 bg-orange-50 text-orange-950",
  source_unavailable: "border-red-300 bg-red-50 text-red-900",
};

function sourceLabel(locale: Locale, state: AdjustmentSourceState) {
  const labels: Record<AdjustmentSourceState, [string, string]> = {
    current: ["Current evidence state", "وضعیت شواهد جاری"],
    stale: ["Evidence changed — re-review required", "شواهد تغییر کرده‌اند — بازبینی مجدد لازم است"],
    legacy_unbound: ["Legacy version — not bound to current evidence", "نسخه قدیمی — به شواهد جاری متصل نیست"],
    source_unavailable: ["Current source unavailable", "منبع جاری در دسترس نیست"],
  };
  return reviewT(locale, ...labels[state]);
}

function treatmentLabel(locale: Locale, value: AdjustmentTreatment) {
  const labels: Record<AdjustmentTreatment, [string, string]> = {
    pending: ["Pending", "در انتظار تصمیم"],
    included: ["Included", "منظور شده"],
    excluded: ["Excluded", "حذف شده"],
    apportioned: ["Apportioned", "تسهیم شده"],
    credit: ["Credit", "اعتبار / کسر"],
  };
  return reviewT(locale, ...labels[value]);
}

function basisLabel(locale: Locale, value: AdjustmentBasis) {
  const labels: Record<AdjustmentBasis, [string, string]> = {
    unallocated: ["Unallocated", "تخصیص‌نیافته"],
    particular_average: ["Particular Average (PA)", "Particular Average (PA)"],
    general_average: ["General Average (GA)", "General Average (GA)"],
    sue_and_labour: ["Sue & Labour", "Sue & Labour"],
    rdc: ["Running Down Clause (RDC)", "Running Down Clause (RDC)"],
    other: ["Other", "سایر"],
    not_applicable: ["Not applicable", "قابل اعمال نیست"],
  };
  return reviewT(locale, ...labels[value]);
}

function controlLabel(locale: Locale, value: ControlKind) {
  const labels: Record<ControlKind, [string, string]> = {
    tax: ["Tax", "مالیات"],
    depreciation: ["Depreciation", "استهلاک"],
    betterment: ["Betterment", "بهبود / Betterment"],
    allocation: ["Allocation", "تخصیص"],
  };
  return reviewT(locale, ...labels[value]);
}

function sourceValue(line: MatureAdjustmentLine, key: string) {
  const value = line.source_snapshot[key];
  return value === undefined || value === null ? "" : String(value);
}

export default function AdjustmentWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [financial, setFinancial] = useState<MatureFinancialReviewResponse | null>(null);
  const [items, setItems] = useState<MatureAdjustmentStatement[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currency, setCurrency] = useState("USD");
  const [reviewNote, setReviewNote] = useState("");
  const [rebaseNote, setRebaseNote] = useState("");
  const [carryStatementControls, setCarryStatementControls] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selected = useMemo(() => items.find((item) => item.id === selectedId) ?? null, [items, selectedId]);
  const canReview = user?.role === "admin" || user?.role === "claims_manager";
  const editable = Boolean(selected && selected.source_state_status === "current" && (selected.status === "draft" || selected.status === "rejected"));

  async function load(preferId?: string) {
    setLoading(true);
    try {
      const [claimData, userData, financialData, statements] = await Promise.all([
        getClaim(id), getCurrentUser(), getMatureFinancialReview(id), listMatureAdjustments(id),
      ]);
      setClaim(claimData);
      setUser(userData);
      setFinancial(financialData);
      setItems(statements.items);
      setCurrency(claimData.currency);
      setSelectedId(preferId ?? selectedId ?? statements.items[0]?.id ?? null);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Adjustment Workspace could not be loaded.", "محیط Adjustment بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [id]);

  function replaceStatement(updated: MatureAdjustmentStatement) {
    setItems((current) => {
      const next = current.some((item) => item.id === updated.id)
        ? current.map((item) => item.id === updated.id ? updated : item)
        : [updated, ...current];
      return [...next].sort((a, b) => b.version - a.version);
    });
  }

  function patchStatement(patch: Partial<MatureAdjustmentStatement>) {
    if (!selectedId) return;
    setItems((current) => current.map((item) => item.id === selectedId ? { ...item, ...patch } : item));
  }

  function patchLine(lineId: string, patch: Partial<MatureAdjustmentLine>) {
    if (!selectedId) return;
    setItems((current) => current.map((item) => item.id === selectedId
      ? { ...item, lines: item.lines.map((line) => line.id === lineId ? { ...line, ...patch } : line) }
      : item));
  }

  function setControls(line: MatureAdjustmentLine, controls: LineFinancialControls) {
    patchLine(line.id, { financial_controls: controls });
  }

  function toggleGroundedControl(line: MatureAdjustmentLine, kind: ControlKind) {
    const controls: LineFinancialControls = { ...(line.financial_controls ?? {}) };
    if (controls[kind]) delete controls[kind];
    else controls[kind] = { amount: null, percentage: null, basis: "", source_reference: "" };
    setControls(line, controls);
  }

  function patchGroundedControl(line: MatureAdjustmentLine, kind: ControlKind, patch: Partial<SourceGroundedControl>) {
    const controls: LineFinancialControls = { ...(line.financial_controls ?? {}) };
    const current = controls[kind] ?? { amount: null, percentage: null, basis: "", source_reference: "" };
    controls[kind] = { ...current, ...patch };
    setControls(line, controls);
  }

  function toggleFx(line: MatureAdjustmentLine) {
    const controls: LineFinancialControls = { ...(line.financial_controls ?? {}) };
    if (controls.fx) delete controls.fx;
    else controls.fx = {
      rate: "",
      source_currency: sourceValue(line, "source_currency") || selected?.currency || "USD",
      target_currency: selected?.currency || "USD",
      rate_date: "",
      source_reference: "",
    };
    setControls(line, controls);
  }

  async function createVersion() {
    setBusy(true); setError("");
    try {
      const created = await createMatureAdjustment(id, { currency, title: claim ? `${claim.claim_reference} – Adjustment Statement` : null });
      replaceStatement(created); setSelectedId(created.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Adjustment draft could not be created.", "پیش‌نویس Adjustment ایجاد نشد."));
    } finally { setBusy(false); }
  }

  async function saveLine(line: MatureAdjustmentLine) {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      replaceStatement(await updateMatureAdjustmentLine(id, selected.id, line.id, {
        treatment: line.treatment,
        basis: line.basis,
        claimed_amount: line.claimed_amount,
        considered_amount: line.considered_amount,
        financial_controls: line.financial_controls,
        reason: line.reason,
        note: line.note,
      }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Adjustment line could not be saved.", "ردیف Adjustment ذخیره نشد."));
      if (e instanceof ApiError && e.status === 409) await load(selected.id);
    } finally { setBusy(false); }
  }

  async function saveStatement() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      replaceStatement(await updateMatureAdjustment(id, selected.id, {
        title: selected.title,
        deductible_amount: selected.deductible_amount,
        deductible_basis: selected.deductible_basis ?? "",
        other_deduction_amount: selected.other_deduction_amount,
        other_deduction_basis: selected.other_deduction_basis ?? "",
      }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Statement controls could not be saved.", "کنترل‌های Statement ذخیره نشد."));
      if (e instanceof ApiError && e.status === 409) await load(selected.id);
    } finally { setBusy(false); }
  }

  async function transition(action: "submit" | "approve" | "reject") {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = action === "submit"
        ? await submitMatureAdjustment(id, selected.id)
        : await reviewMatureAdjustment(id, selected.id, action, reviewNote.trim());
      replaceStatement(updated); setReviewNote("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Adjustment status could not be updated.", "وضعیت Adjustment به‌روزرسانی نشد."));
      if (e instanceof ApiError && e.status === 409) await load(selected.id);
    } finally { setBusy(false); }
  }

  async function rebaseSelected() {
    if (!selected || rebaseNote.trim().length < 3) return;
    setBusy(true); setError("");
    try {
      const rebased = await rebaseMatureAdjustment(id, selected.id, {
        carry_statement_controls: carryStatementControls,
        note: rebaseNote.trim(),
      });
      replaceStatement(rebased); setSelectedId(rebased.id); setRebaseNote(""); setCarryStatementControls(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Rebase could not be completed.", "Rebase انجام نشد."));
      await load(selected.id);
    } finally { setBusy(false); }
  }

  if (loading) return <div className="panel p-6 text-sm text-slate-600">{r("Loading Adjustment Workspace…", "در حال بارگذاری محیط Adjustment…")}</div>;
  if (!claim || !financial) return <div className="panel p-6 text-sm text-red-700">{error || r("Adjustment data is unavailable.", "داده‌های Adjustment در دسترس نیست.")}</div>;

  const currencies = Array.from(new Set([claim.currency, ...Object.keys(financial.totals_by_currency)])).sort();
  const reserve = financial.reserve_history.find((row) => row.currency === selected?.currency);

  return <div>
    <Link href={`/claims/${id}/financial`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r("← Back to Financial Review", "→ بازگشت به بازبینی مالی")}</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
      <div>
        <p className="eyebrow" dir="auto">{claim.claim_reference} · {r("Human financial control", "کنترل مالی انسانی")}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Adjustment Workspace", "محیط Adjustment")}</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500" dir="auto">{r(
          "Build immutable, source-bound Adjustment versions from current reviewed invoice evidence. FX, tax, depreciation, betterment, allocation and deductible inputs remain human decisions; arithmetic never creates payment, reserve or coverage authority.",
          "نسخه‌های تغییرناپذیر و متصل به شواهد Adjustment را از صورتحساب‌های بازبینی‌شده جاری بسازید. FX، مالیات، استهلاک، Betterment، تخصیص و فرانشیز همگی ورودی و تصمیم انسانی هستند و محاسبات سیستم هیچ اختیار خودکاری برای پرداخت، ذخیره یا پوشش ایجاد نمی‌کند."
        )}</p>
      </div>
      <div className="flex flex-wrap gap-2"><select className="field min-w-28" value={currency} onChange={(e) => setCurrency(e.target.value)} dir="ltr">{currencies.map((value) => <option key={value}>{value}</option>)}</select><button className="primary-button whitespace-nowrap" disabled={busy} onClick={createVersion}>{r("Create current version", "ایجاد نسخه جاری")}</button></div>
    </div>

    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700" dir="auto">{error}</div> : null}

    <div className="mt-6 grid gap-6 xl:grid-cols-[310px_minmax(0,1fr)]">
      <aside className="panel p-4">
        <h2 className="px-2 text-sm font-semibold text-slate-950">{r("Adjustment versions", "نسخه‌های Adjustment")}</h2>
        <p className="px-2 text-xs text-slate-500" dir="auto">{r("Approved versions remain immutable even when later evidence changes.", "نسخه‌های تأییدشده حتی پس از تغییر شواهد نیز تغییرناپذیر می‌مانند.")}</p>
        <div className="mt-3 space-y-2">{items.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full rounded-xl border p-3 text-start ${item.id === selectedId ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white"}`}>
          <div className="flex items-center justify-between gap-2"><p className="font-semibold text-slate-900">{r("Version", "نسخه")} {item.version}</p><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${statusTone[item.status] ?? "bg-slate-100"}`}>{item.status.replaceAll("_", " ")}</span></div>
          <p className="mt-2 text-xs text-slate-500" dir="ltr">{item.currency} · {item.lines.length} {r("line(s)", "ردیف")}</p><p className="mt-1 text-sm font-semibold text-slate-800" dir="ltr">{formatMoney(item.net_adjusted, item.currency)}</p><p className="mt-2 text-[11px] font-semibold" dir="auto">{sourceLabel(locale, item.source_state_status)}</p>
        </button>)}{!items.length ? <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500" dir="auto">{r("No Adjustment version yet. Create one from current reviewed invoice evidence.", "هنوز نسخه‌ای از Adjustment وجود ندارد. یک نسخه از شواهد صورتحساب بازبینی‌شده جاری ایجاد کنید.")}</div> : null}</div>
      </aside>

      <main>{!selected ? <div className="panel p-12 text-center text-sm text-slate-500">{r("No Adjustment version selected.", "هیچ نسخه‌ای از Adjustment انتخاب نشده است.")}</div> : <>
        <section className={`rounded-xl border p-5 ${sourceTone[selected.source_state_status]}`}>
          <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
            <div><p className="font-semibold" dir="auto">{sourceLabel(locale, selected.source_state_status)}</p><p className="mt-1 text-xs leading-5" dir="auto">{selected.source_state_status === "current" ? r("This version is bound to the current Financial Review evidence state.", "این نسخه به وضعیت فعلی شواهد Financial Review متصل است.") : r("Do not edit, submit or approve this historical state. Create a deliberate rebased version against current evidence.", "این وضعیت تاریخی را ویرایش، ارسال یا تأیید نکنید. یک نسخه جدید را آگاهانه بر اساس شواهد جاری Rebase کنید.")}</p><p className="mt-2 text-xs" dir="ltr">+{selected.source_change_summary.added_count} / −{selected.source_change_summary.removed_count} / Δ{selected.source_change_summary.changed_count}{selected.source_state_hash ? ` · ${selected.source_state_hash.slice(0, 12)}…` : " · legacy"}</p></div>
            {selected.source_state_status !== "current" ? <div className="w-full max-w-lg rounded-lg border border-current/20 bg-white/60 p-3"><textarea className="field min-h-20" value={rebaseNote} onChange={(e) => setRebaseNote(e.target.value)} placeholder={r("Why are you rebasing to current evidence?", "دلیل Rebase به شواهد جاری چیست؟")} dir="auto" /><label className="mt-2 flex items-start gap-2 text-xs" dir="auto"><input type="checkbox" checked={carryStatementControls} onChange={(e) => setCarryStatementControls(e.target.checked)} /><span>{r("Carry statement-level deductible/other deduction controls. Changed line judgments are never carried automatically.", "کنترل‌های سطح Statement مانند فرانشیز/کسورات دیگر منتقل شوند. قضاوت ردیف‌های تغییرکرده هرگز خودکار منتقل نمی‌شود.")}</span></label><button className="primary-button mt-3" disabled={busy || rebaseNote.trim().length < 3} onClick={rebaseSelected}>{r("Rebase to current evidence", "Rebase به شواهد جاری")}</button></div> : null}
          </div>
        </section>

        <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="panel p-5"><p className="metric-label">{r("Gross claimed", "مبلغ ناخالص مطالبه")}</p><p className="metric-value text-xl" dir="ltr">{formatMoney(selected.gross_claimed, selected.currency)}</p></div>
          <div className="panel p-5"><p className="metric-label">{r("Gross considered", "مبلغ ناخالص مورد بررسی")}</p><p className="metric-value text-xl" dir="ltr">{formatMoney(selected.gross_considered, selected.currency)}</p></div>
          <div className="panel p-5"><p className="metric-label">{r("Adjusted total", "جمع تعدیل‌شده")}</p><p className="metric-value text-xl" dir="ltr">{formatMoney(selected.net_adjusted, selected.currency)}</p><p className="mt-1 text-xs text-slate-400">{r("Not payment authority", "مجوز پرداخت نیست")}</p></div>
          <div className="panel p-5"><p className="metric-label">{r("Current reserve", "ذخیره فعلی")}</p><p className="metric-value text-xl" dir="ltr">{reserve ? formatMoney(reserve.amount, reserve.currency) : r("Not recorded", "ثبت نشده")}</p><p className="mt-1 text-xs text-slate-400">{r("Comparison only; never auto-updated", "فقط برای مقایسه؛ هرگز خودکار تغییر نمی‌کند")}</p></div>
        </section>

        <section className="panel mt-6 p-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0 flex-1"><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500" dir="ltr">Version {selected.version} · {selected.currency}</p>{editable ? <input className="field mt-2 text-lg font-semibold" value={selected.title} onChange={(e) => patchStatement({ title: e.target.value })} dir="auto" /> : <h2 className="mt-1 text-xl font-semibold text-slate-950" dir="auto">{selected.title}</h2>}{selected.rebased_from_statement_id ? <p className="mt-1 text-xs text-slate-400" dir="ltr">Rebased from {selected.rebased_from_statement_id.slice(0, 8)}…</p> : null}</div><span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${statusTone[selected.status] ?? "bg-slate-100"}`}>{selected.status.replaceAll("_", " ")}</span></div>
          <div className="mt-5 space-y-4">{selected.lines.map((line) => {
            const sourceCurrency = sourceValue(line, "source_currency") || selected.currency;
            const sourceAmount = sourceValue(line, "source_amount") || line.claimed_amount;
            const crossCurrency = sourceCurrency !== selected.currency;
            return <div key={line.id} className="rounded-xl border border-slate-200 p-4">
              <div className="grid gap-4 xl:grid-cols-[minmax(220px,1.3fr)_160px_170px_170px_150px]">
                <div><p className="text-xs font-semibold text-slate-400" dir="ltr">#{line.sort_order} · {sourceCurrency} {sourceAmount} · v{sourceValue(line, "document_version") || "?"}</p><p className="mt-1 font-semibold text-slate-900" dir="auto">{line.description}</p><p className="mt-1 text-xs text-slate-500" dir="auto">{line.supplier || r("Supplier not stated", "تأمین‌کننده مشخص نشده")} · {line.document_number || "—"} · {line.category || r("Uncategorised", "بدون دسته")}</p></div>
                <label><span className="label">{r("Claimed", "مطالبه‌شده")} ({selected.currency})</span><input disabled={!editable || !crossCurrency} type="number" min="0" step="0.01" className="field" value={line.claimed_amount} onChange={(e) => patchLine(line.id, { claimed_amount: e.target.value })} dir="ltr" /></label>
                <label><span className="label">{r("Treatment", "نحوه رسیدگی")}</span><select disabled={!editable} className="field" value={line.treatment} onChange={(e) => patchLine(line.id, { treatment: e.target.value as AdjustmentTreatment })}>{treatments.map((value) => <option key={value} value={value}>{treatmentLabel(locale, value)}</option>)}</select></label>
                <label><span className="label">{r("Basis", "مبنای تعدیل")}</span><select disabled={!editable} className="field" value={line.basis} onChange={(e) => patchLine(line.id, { basis: e.target.value as AdjustmentBasis })}>{bases.map((value) => <option key={value} value={value}>{basisLabel(locale, value)}</option>)}</select></label>
                <label><span className="label">{r("Considered", "مورد قبول برای بررسی")}</span><input disabled={!editable} type="number" step="0.01" className="field" value={line.considered_amount} onChange={(e) => patchLine(line.id, { considered_amount: e.target.value })} dir="ltr" /></label>
              </div>

              {crossCurrency ? <div className="mt-4 rounded-lg border border-cyan-200 bg-cyan-50 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-cyan-950">{r("Human-entered FX conversion required", "تبدیل FX با ورود اطلاعات انسانی الزامی است")}</p><p className="text-xs text-cyan-800" dir="auto">{r("The platform verifies source amount × your rate. It never selects the rate or date.", "سیستم فقط مبلغ منبع × نرخ واردشده توسط شما را کنترل می‌کند و هیچ نرخ یا تاریخی را انتخاب نمی‌کند.")}</p></div>{editable ? <button className="secondary-button px-3 py-2 text-xs" onClick={() => toggleFx(line)}>{line.financial_controls?.fx ? r("Remove FX input", "حذف ورودی FX") : r("Add FX input", "افزودن ورودی FX")}</button> : null}</div>{line.financial_controls?.fx ? <div className="mt-3 grid gap-3 md:grid-cols-4"><label><span className="label">{r("Rate", "نرخ")}</span><input disabled={!editable} className="field" type="number" step="0.000001" value={line.financial_controls.fx.rate} onChange={(e) => setControls(line, { ...line.financial_controls, fx: { ...line.financial_controls.fx!, rate: e.target.value } })} dir="ltr" /></label><label><span className="label">{r("Rate date", "تاریخ نرخ")}</span><input disabled={!editable} className="field" type="date" value={line.financial_controls.fx.rate_date} onChange={(e) => setControls(line, { ...line.financial_controls, fx: { ...line.financial_controls.fx!, rate_date: e.target.value } })} dir="ltr" /></label><div><span className="label">{r("Currency pair", "جفت ارز")}</span><p className="field bg-white" dir="ltr">{sourceCurrency} → {selected.currency}</p></div><label><span className="label">{r("Rate source", "منبع نرخ")}</span><input disabled={!editable} className="field" value={line.financial_controls.fx.source_reference} onChange={(e) => setControls(line, { ...line.financial_controls, fx: { ...line.financial_controls.fx!, source_reference: e.target.value } })} dir="auto" /></label></div> : null}</div> : null}

              <details className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-800">{r("Structured human controls: tax / depreciation / betterment / allocation", "کنترل‌های ساختاری انسانی: مالیات / استهلاک / Betterment / تخصیص")}</summary><p className="mt-2 text-xs text-slate-500" dir="auto">{r("These fields record your source-grounded inputs. Percentage arithmetic is a reference only and never determines recoverability.", "این فیلدها ورودی‌های مستند شما را ثبت می‌کنند. محاسبه درصد صرفاً مرجع است و قابلیت بازیافت را تعیین نمی‌کند.")}</p><div className="mt-3 grid gap-3 xl:grid-cols-2">{controlKinds.map((kind) => {
                const control = line.financial_controls?.[kind];
                return <div key={kind} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex items-center justify-between"><p className="font-semibold text-slate-800">{controlLabel(locale, kind)}</p>{editable ? <button className="text-xs font-semibold text-cyan-700" onClick={() => toggleGroundedControl(line, kind)}>{control ? r("Remove", "حذف") : r("Add", "افزودن")}</button> : null}</div>{control ? <div className="mt-3 grid gap-2 md:grid-cols-2"><label><span className="label">{r("Amount", "مبلغ")}</span><input disabled={!editable} type="number" min="0" step="0.01" className="field" value={control.amount ?? ""} onChange={(e) => patchGroundedControl(line, kind, { amount: e.target.value || null })} dir="ltr" /></label><label><span className="label">{r("Percentage", "درصد")}</span><input disabled={!editable} type="number" min="0" max="100" step="0.01" className="field" value={control.percentage ?? ""} onChange={(e) => patchGroundedControl(line, kind, { percentage: e.target.value || null })} dir="ltr" /></label><label className="md:col-span-2"><span className="label">{r("Human basis", "مبنای انسانی")}</span><input disabled={!editable} className="field" value={control.basis} onChange={(e) => patchGroundedControl(line, kind, { basis: e.target.value })} dir="auto" /></label><label className="md:col-span-2"><span className="label">{r("Source reference", "مرجع منبع")}</span><input disabled={!editable} className="field" value={control.source_reference} onChange={(e) => patchGroundedControl(line, kind, { source_reference: e.target.value })} dir="auto" /></label>{control.computed_reference_amount ? <p className="md:col-span-2 text-xs text-slate-500" dir="ltr">{r("Computed reference", "مبلغ مرجع محاسبه‌شده")}: {formatMoney(control.computed_reference_amount, selected.currency)}</p> : null}</div> : <p className="mt-2 text-xs text-slate-400">{r("No human control recorded.", "کنترل انسانی ثبت نشده است.")}</p>}</div>;
              })}</div></details>

              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_auto]"><label><span className="label">{r("Reason / adjustment basis", "دلیل / مبنای تعدیل")}</span><textarea disabled={!editable} className="field min-h-20" value={line.reason ?? ""} onChange={(e) => patchLine(line.id, { reason: e.target.value })} placeholder={r("Required for exclusions, apportionments, credits and amount differences", "برای حذف، تسهیم، اعتبار و اختلاف مبلغ الزامی است")} dir="auto" /></label><label><span className="label">{r("Reviewer note", "یادداشت بازبین")}</span><textarea disabled={!editable} className="field min-h-20" value={line.note ?? ""} onChange={(e) => patchLine(line.id, { note: e.target.value })} dir="auto" /></label>{editable ? <button className="secondary-button self-end" disabled={busy} onClick={() => saveLine(line)}>{r("Save line", "ذخیره ردیف")}</button> : null}</div>
            </div>;
          })}</div>
        </section>

        <section className="panel mt-6 p-6"><h2 className="section-title">{r("Statement-level controls", "کنترل‌های سطح Statement")}</h2><p className="section-subtitle" dir="auto">{r("These amounts are entered by the claims professional. Policy interpretation and recoverability remain human decisions.", "این مبالغ توسط کارشناس خسارت وارد می‌شوند. تفسیر بیمه‌نامه و قابلیت بازیافت همچنان تصمیم انسانی است.")}</p><div className="mt-5 grid gap-4 lg:grid-cols-2"><div className="rounded-xl border border-slate-200 p-4"><label><span className="label">{r("Deductible", "فرانشیز")} ({selected.currency})</span><input disabled={!editable} type="number" min="0" step="0.01" className="field" value={selected.deductible_amount} onChange={(e) => patchStatement({ deductible_amount: e.target.value })} dir="ltr" /></label><label className="mt-3 block"><span className="label">{r("Deductible basis", "مبنای فرانشیز")}</span><textarea disabled={!editable} className="field min-h-24" value={selected.deductible_basis ?? ""} onChange={(e) => patchStatement({ deductible_basis: e.target.value })} placeholder={r("Policy clause, wording and human review basis", "کلوز بیمه‌نامه، متن و مبنای بازبینی انسانی")} dir="auto" /></label></div><div className="rounded-xl border border-slate-200 p-4"><label><span className="label">{r("Other deduction / credit", "کسورات / اعتبار دیگر")} ({selected.currency})</span><input disabled={!editable} type="number" min="0" step="0.01" className="field" value={selected.other_deduction_amount} onChange={(e) => patchStatement({ other_deduction_amount: e.target.value })} dir="ltr" /></label><label className="mt-3 block"><span className="label">{r("Other deduction / credit basis", "مبنای کسورات / اعتبار دیگر")}</span><textarea disabled={!editable} className="field min-h-24" value={selected.other_deduction_basis ?? ""} onChange={(e) => patchStatement({ other_deduction_basis: e.target.value })} dir="auto" /></label></div></div>{editable ? <div className="mt-4 flex flex-wrap gap-2"><button className="secondary-button" disabled={busy} onClick={saveStatement}>{r("Save statement controls", "ذخیره کنترل‌های Statement")}</button><button className="primary-button" disabled={busy} onClick={() => transition("submit")}>{r("Submit for Manager review", "ارسال برای بازبینی مدیر")}</button></div> : null}</section>

        {selected.status === "under_review" && canReview ? <section className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-5"><h2 className="text-sm font-semibold text-amber-950">{r("Manager review", "بازبینی مدیر")}</h2><p className="mt-1 text-xs leading-5 text-amber-800" dir="auto">{r("Approval confirms human review of line treatments, source-grounded controls and arithmetic against the exact current evidence state. It is not payment authorization.", "تأیید به معنای بازبینی انسانی نحوه رسیدگی ردیف‌ها، کنترل‌های مستند و محاسبات در برابر وضعیت دقیق شواهد جاری است و مجوز پرداخت نیست.")}</p>{selected.source_state_status !== "current" ? <p className="mt-2 font-semibold text-red-700">{r("Approval is blocked until a current rebased version is created.", "تا زمان ایجاد نسخه Rebase‌شده جاری، تأیید مسدود است.")}</p> : null}<textarea className="field mt-3 min-h-24" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder={r("Record review against evidence and applicable wording.", "بازبینی نسبت به شواهد و متن قابل اعمال را ثبت کنید.")} dir="auto" /><div className="mt-3 flex gap-2"><button className="primary-button" disabled={busy || reviewNote.trim().length < 3 || selected.source_state_status !== "current"} onClick={() => transition("approve")}>{r("Approve immutable version", "تأیید نسخه تغییرناپذیر")}</button><button className="secondary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("reject")}>{r("Reject for revision", "رد برای اصلاح")}</button></div></section> : null}

        {selected.status === "approved" ? <section className="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 p-5"><p className="font-semibold text-emerald-900">{r("Immutable human-reviewed Adjustment", "Adjustment تغییرناپذیر بازبینی‌شده توسط انسان")}</p><p className="mt-1 text-xs text-emerald-800" dir="auto">{r("Historical values and content hash remain fixed. Later evidence changes only make this version historical/stale; they do not rewrite it or any existing Settlement/Payment record.", "مقادیر تاریخی و Content Hash ثابت می‌مانند. تغییرات بعدی شواهد فقط این نسخه را تاریخی/Stale می‌کنند و آن یا Settlement/Payment موجود را بازنویسی نمی‌کنند.")}</p><p className="mt-2 break-all text-xs" dir="ltr">{selected.content_hash}</p></section> : null}
      </>}</main>
    </div>
  </div>;
}
