"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { reviewT } from "@/lib/i18n-review-support";
import {
  createRecoveryCounterparty,
  createTimebarScenario,
  getRecoveryMaturity,
  reviewTimebarScenario,
  reviseRecoveryCounterparty,
  reviseTimebarScenario,
  type PeriodUnit,
  type RecoveryCounterparty,
  type RecoveryMaturityDashboard,
  type ScenarioReviewAction,
  type TimebarScenario,
} from "@/lib/recovery-timebar-api";
import type { Claim } from "@/lib/types";

const emptyCounterparty = {
  name: "",
  role: "",
  allegation_basis: "",
  source_reference: "",
  source_document_id: "",
};

const emptyScenario = {
  title: "",
  legal_basis: "",
  source_reference: "",
  source_document_id: "",
  counterparty_id: "",
  anchor_date: "",
  period_value: "",
  period_unit: "months" as PeriodUnit,
  extension_value: "",
  extension_unit: "days" as PeriodUnit,
  extension_basis: "",
  assumptions: "",
};

function sourceTone(status: string) {
  if (status === "current") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "reference_only") return "border-slate-200 bg-slate-50 text-slate-700";
  return "border-amber-300 bg-amber-50 text-amber-900";
}

export default function RecoveryMaturityPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [dashboard, setDashboard] = useState<RecoveryMaturityDashboard | null>(null);
  const [counterpartyForm, setCounterpartyForm] = useState(emptyCounterparty);
  const [counterpartyEdit, setCounterpartyEdit] = useState<RecoveryCounterparty | null>(null);
  const [scenarioForm, setScenarioForm] = useState(emptyScenario);
  const [scenarioEdit, setScenarioEdit] = useState<TimebarScenario | null>(null);
  const [reviewScenario, setReviewScenario] = useState<TimebarScenario | null>(null);
  const [reviewAction, setReviewAction] = useState<ScenarioReviewAction>("confirm");
  const [reviewNote, setReviewNote] = useState("");
  const [overrideDate, setOverrideDate] = useState("");
  const [reviewSource, setReviewSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [claimData, maturity] = await Promise.all([getClaim(id), getRecoveryMaturity(id)]);
      setClaim(claimData);
      setDashboard(maturity);
      if (reviewScenario) {
        setReviewScenario(maturity.scenarios.find((row) => row.scenario_key === reviewScenario.scenario_key) ?? null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Recovery maturity workspace could not be loaded.", "محیط تکامل‌یافته بازیافت بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [id]);

  async function saveCounterparty() {
    if ([counterpartyForm.name, counterpartyForm.role, counterpartyForm.allegation_basis, counterpartyForm.source_reference].some((value) => value.trim().length < 2)) {
      setError(r("Complete the counterparty role, allegation basis and source reference.", "نقش طرف مقابل، مبنای ادعا و مرجع منبع را کامل کنید."));
      return;
    }
    setBusy(true); setError("");
    const payload = {
      name: counterpartyForm.name.trim(),
      role: counterpartyForm.role.trim(),
      allegation_basis: counterpartyForm.allegation_basis.trim(),
      source_reference: counterpartyForm.source_reference.trim(),
      source_document_id: counterpartyForm.source_document_id.trim() || null,
    };
    try {
      if (counterpartyEdit) {
        await reviseRecoveryCounterparty(id, counterpartyEdit.counterparty_key, {
          ...payload,
          expected_record_hash: counterpartyEdit.record_hash,
        });
      } else {
        await createRecoveryCounterparty(id, payload);
      }
      setCounterpartyEdit(null); setCounterpartyForm(emptyCounterparty); await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Counterparty context could not be saved.", "اطلاعات طرف مقابل ذخیره نشد."));
    } finally { setBusy(false); }
  }

  function editCounterparty(row: RecoveryCounterparty) {
    setCounterpartyEdit(row);
    setCounterpartyForm({
      name: row.name,
      role: row.role,
      allegation_basis: row.allegation_basis,
      source_reference: row.source_reference,
      source_document_id: row.source_document_id ?? "",
    });
  }

  async function saveScenario() {
    if (!scenarioForm.title.trim() || !scenarioForm.legal_basis.trim() || !scenarioForm.source_reference.trim() || !scenarioForm.anchor_date || !scenarioForm.period_value || !scenarioForm.assumptions.trim()) {
      setError(r("Complete the scenario basis, source, anchor date, period and assumptions.", "مبنا، منبع، تاریخ مبنا، دوره و فرضیات سناریو را کامل کنید."));
      return;
    }
    const extension = scenarioForm.extension_value ? Number(scenarioForm.extension_value) : null;
    const payload = {
      title: scenarioForm.title.trim(),
      legal_basis: scenarioForm.legal_basis.trim(),
      source_reference: scenarioForm.source_reference.trim(),
      source_document_id: scenarioForm.source_document_id.trim() || null,
      counterparty_id: scenarioForm.counterparty_id || null,
      anchor_date: scenarioForm.anchor_date,
      period_value: Number(scenarioForm.period_value),
      period_unit: scenarioForm.period_unit,
      extension_value: extension,
      extension_unit: extension === null ? null : scenarioForm.extension_unit,
      extension_basis: extension === null ? null : scenarioForm.extension_basis.trim() || null,
      assumptions: scenarioForm.assumptions.trim(),
    };
    setBusy(true); setError("");
    try {
      if (scenarioEdit) {
        await reviseTimebarScenario(id, scenarioEdit.scenario_key, {
          ...payload,
          expected_scenario_hash: scenarioEdit.scenario_hash,
        });
      } else {
        await createTimebarScenario(id, payload);
      }
      setScenarioEdit(null); setScenarioForm(emptyScenario); await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Time-bar scenario could not be saved.", "سناریوی مهلت زمانی ذخیره نشد."));
    } finally { setBusy(false); }
  }

  function editScenario(row: TimebarScenario) {
    setScenarioEdit(row);
    setScenarioForm({
      title: row.title,
      legal_basis: row.legal_basis,
      source_reference: row.source_reference,
      source_document_id: row.source_document_id ?? "",
      counterparty_id: row.counterparty_id ?? "",
      anchor_date: row.anchor_date,
      period_value: String(row.period_value),
      period_unit: row.period_unit,
      extension_value: row.extension_value === null ? "" : String(row.extension_value),
      extension_unit: row.extension_unit ?? "days",
      extension_basis: row.extension_basis ?? "",
      assumptions: row.assumptions,
    });
  }

  async function submitReview() {
    if (!reviewScenario || reviewNote.trim().length < 5) return;
    if (reviewAction === "override" && (!overrideDate || reviewSource.trim().length < 3)) {
      setError(r("Override requires a human-entered deadline and source reference.", "Override به تاریخ واردشده توسط انسان و مرجع منبع نیاز دارد."));
      return;
    }
    setBusy(true); setError("");
    try {
      await reviewTimebarScenario(id, reviewScenario.id, {
        action: reviewAction,
        scenario_hash: reviewScenario.scenario_hash,
        confirmed_deadline: reviewAction === "override" ? overrideDate : null,
        note: reviewNote.trim(),
        source_reference: reviewAction === "override" ? reviewSource.trim() : null,
      });
      setReviewNote(""); setOverrideDate(""); setReviewSource(""); await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Human/legal review could not be recorded.", "بازبینی انسانی/حقوقی ثبت نشد."));
    } finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">{r("Loading recovery maturity…", "در حال بارگذاری محیط تکامل‌یافته بازیافت…")}</div>;
  if (!claim || !dashboard) return <div className="panel p-6 text-sm text-red-700">{error || r("Claim unavailable.", "پرونده در دسترس نیست.")}</div>;

  return <div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Link href={`/claims/${id}/recovery-timebar`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r("← Recovery intelligence", "→ بازگشت به هوشمندی بازیافت")}</Link>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r("Claim overview", "نمای کلی پرونده")}</Link>
    </div>

    <div className="mt-5">
      <p className="eyebrow"><span dir="ltr">{claim.claim_reference}</span> · {r("Recovery maturity", "تکامل بازیافت")}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Recovery counterparties & time-bar scenarios", "طرف‌های احتمالی بازیافت و سناریوهای مهلت زمانی")}</h1>
      <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">{r("Record multiple human hypotheses without turning them into platform findings. Candidate dates are calendar arithmetic only; a confirmed or overridden deadline is a separate Manager/Admin review.", "چند فرضیه انسانی را بدون تبدیل آنها به نتیجه سیستم ثبت کنید. تاریخ‌های پیشنهادی فقط محاسبه تقویمی هستند؛ تأیید یا تغییر مهلت یک بازبینی جداگانه توسط مدیر است.")}</p>
    </div>

    <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-900" dir="auto">
      <strong>{r("No automated legal conclusion.", "هیچ نتیجه حقوقی خودکاری وجود ندارد.")}</strong> {dashboard.disclaimer}
    </div>
    {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">{error}</div> : null}

    <div className="mt-6 grid gap-6 xl:grid-cols-2">
      <section className="panel p-5">
        <h2 className="section-title">{r("Potential counterparties", "طرف‌های احتمالی")}</h2>
        <p className="section-subtitle">{r("Human allegation/role context only — never a platform finding of fault or liability.", "فقط زمینه ادعایی/نقش ثبت‌شده توسط انسان — نه نتیجه سیستم درباره تقصیر یا مسئولیت.")}</p>
        <div className="mt-4 space-y-3">
          {dashboard.counterparties.length ? dashboard.counterparties.map((row) => <div key={row.id} className="rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-semibold text-slate-950" dir="auto">{row.name}</h3><p className="mt-1 text-xs text-slate-500" dir="auto">{row.role} · v{row.version}</p></div><span className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${sourceTone(row.source_state_status)}`}>{row.source_state_status.replaceAll("_", " ")}</span></div>
            <p className="mt-3 text-sm leading-6 text-slate-600" dir="auto">{row.allegation_basis}</p>
            <p className="mt-2 text-xs text-slate-400" dir="auto">{r("Source", "منبع")}: {row.source_reference}</p>
            <button className="secondary-button mt-3" onClick={() => editCounterparty(row)}>{r("Create revised version", "ایجاد نسخه اصلاح‌شده")}</button>
          </div>) : <p className="text-sm text-slate-400">{r("No structured counterparties yet.", "هنوز طرف احتمالی ساختاریافته‌ای ثبت نشده است.")}</p>}
        </div>

        <div className="mt-5 border-t border-slate-200 pt-5">
          <h3 className="text-sm font-semibold text-slate-950">{counterpartyEdit ? r("Revise counterparty", "اصلاح طرف احتمالی") : r("Add counterparty", "افزودن طرف احتمالی")}</h3>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label><span className="label">{r("Name", "نام")}</span><input className="field" value={counterpartyForm.name} onChange={(e) => setCounterpartyForm({ ...counterpartyForm, name: e.target.value })} /></label>
            <label><span className="label">{r("Human-assigned role", "نقش تعیین‌شده توسط انسان")}</span><input className="field" value={counterpartyForm.role} onChange={(e) => setCounterpartyForm({ ...counterpartyForm, role: e.target.value })} /></label>
          </div>
          <label className="mt-3 block"><span className="label">{r("Allegation / investigation basis", "مبنای ادعا / تحقیق")}</span><textarea className="field min-h-24" value={counterpartyForm.allegation_basis} onChange={(e) => setCounterpartyForm({ ...counterpartyForm, allegation_basis: e.target.value })} /></label>
          <label className="mt-3 block"><span className="label">{r("Source reference", "مرجع منبع")}</span><input className="field" value={counterpartyForm.source_reference} onChange={(e) => setCounterpartyForm({ ...counterpartyForm, source_reference: e.target.value })} /></label>
          <label className="mt-3 block"><span className="label">{r("Current document ID (optional)", "شناسه سند فعلی (اختیاری)")}</span><input className="field font-mono text-xs" dir="ltr" value={counterpartyForm.source_document_id} onChange={(e) => setCounterpartyForm({ ...counterpartyForm, source_document_id: e.target.value })} /></label>
          <div className="mt-4 flex gap-2"><button disabled={busy} className="primary-button" onClick={saveCounterparty}>{busy ? r("Working…", "در حال انجام…") : r("Save human context", "ذخیره زمینه انسانی")}</button>{counterpartyEdit ? <button className="secondary-button" onClick={() => { setCounterpartyEdit(null); setCounterpartyForm(emptyCounterparty); }}>{r("Cancel revision", "لغو اصلاح")}</button> : null}</div>
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="section-title">{r("Alternative time-bar scenarios", "سناریوهای جایگزین مهلت زمانی")}</h2>
        <p className="section-subtitle">{r("The platform computes only from the anchor, period and extension assumptions you enter.", "سیستم فقط بر اساس تاریخ مبنا، دوره و فرض تمدیدی که شما وارد می‌کنید محاسبه می‌کند.")}</p>
        <div className="mt-4 space-y-3">{dashboard.scenarios.length ? dashboard.scenarios.map((row) => <div key={row.id} className="rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-semibold text-slate-950" dir="auto">{row.title}</h3><p className="mt-1 text-xs text-slate-500">v{row.version} · {row.period_value} {row.period_unit}</p></div><span className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${sourceTone(row.source_state_status)}`}>{row.source_state_status.replaceAll("_", " ")}</span></div>
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2"><div><dt className="detail-label">{r("Human anchor", "تاریخ مبنای انسانی")}</dt><dd dir="ltr">{formatDate(row.anchor_date)}</dd></div><div><dt className="detail-label">{r("Candidate only", "فقط تاریخ پیشنهادی")}</dt><dd className="font-semibold" dir="ltr">{formatDate(row.candidate_deadline)}</dd></div></dl>
          <p className="mt-3 text-sm text-slate-600" dir="auto">{row.legal_basis}</p>
          <p className="mt-2 text-xs text-slate-400" dir="auto">{r("Assumptions", "فرضیات")}: {row.assumptions}</p>
          {row.latest_review ? <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-3 text-xs text-violet-900"><strong>{r("Latest human/legal review", "آخرین بازبینی انسانی/حقوقی")}</strong> · #{row.latest_review.review_number} · {row.latest_review.action}{row.latest_review.confirmed_deadline ? <> · <span dir="ltr">{formatDate(row.latest_review.confirmed_deadline)}</span></> : null}</div> : null}
          <div className="mt-3 flex flex-wrap gap-2"><button className="secondary-button" onClick={() => editScenario(row)}>{r("Create revised version", "ایجاد نسخه اصلاح‌شده")}</button><button disabled={row.source_state_status === "stale" || row.source_state_status === "source_unavailable"} className="secondary-button" onClick={() => setReviewScenario(row)}>{r("Human/legal review", "بازبینی انسانی/حقوقی")}</button></div>
        </div>) : <p className="text-sm text-slate-400">{r("No alternative scenarios yet.", "هنوز سناریوی جایگزینی ثبت نشده است.")}</p>}</div>
      </section>
    </div>

    <section className="panel mt-6 p-5">
      <h2 className="section-title">{scenarioEdit ? r("Revise time-bar scenario", "اصلاح سناریوی مهلت زمانی") : r("Create alternative time-bar scenario", "ایجاد سناریوی جایگزین مهلت زمانی")}</h2>
      <p className="section-subtitle">{r("Do not enter a candidate deadline. It is computed from your explicit inputs and remains non-authoritative until a separate human/legal review.", "تاریخ پیشنهادی را وارد نکنید. این تاریخ از ورودی‌های صریح شما محاسبه می‌شود و تا بازبینی جداگانه انسانی/حقوقی معتبر نیست.")}</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label><span className="label">{r("Scenario title", "عنوان سناریو")}</span><input className="field" value={scenarioForm.title} onChange={(e) => setScenarioForm({ ...scenarioForm, title: e.target.value })} /></label>
        <label><span className="label">{r("Potential counterparty (optional)", "طرف احتمالی (اختیاری)")}</span><select className="field" value={scenarioForm.counterparty_id} onChange={(e) => setScenarioForm({ ...scenarioForm, counterparty_id: e.target.value })}><option value="">{r("None selected", "انتخاب نشده")}</option>{dashboard.counterparties.map((row) => <option key={row.id} value={row.id}>{row.name} · v{row.version}</option>)}</select></label>
        <label className="md:col-span-2"><span className="label">{r("Human-entered legal/factual basis", "مبنای حقوقی/واقعی واردشده توسط انسان")}</span><textarea className="field min-h-24" value={scenarioForm.legal_basis} onChange={(e) => setScenarioForm({ ...scenarioForm, legal_basis: e.target.value })} /></label>
        <label><span className="label">{r("Source reference", "مرجع منبع")}</span><input className="field" value={scenarioForm.source_reference} onChange={(e) => setScenarioForm({ ...scenarioForm, source_reference: e.target.value })} /></label>
        <label><span className="label">{r("Current document ID (optional)", "شناسه سند فعلی (اختیاری)")}</span><input className="field font-mono text-xs" dir="ltr" value={scenarioForm.source_document_id} onChange={(e) => setScenarioForm({ ...scenarioForm, source_document_id: e.target.value })} /></label>
        <label><span className="label">{r("Human-selected anchor date", "تاریخ مبنای انتخاب‌شده توسط انسان")}</span><input type="date" className="field" dir="ltr" value={scenarioForm.anchor_date} onChange={(e) => setScenarioForm({ ...scenarioForm, anchor_date: e.target.value })} /></label>
        <div className="grid grid-cols-2 gap-2"><label><span className="label">{r("Period", "دوره")}</span><input type="number" min="1" className="field" dir="ltr" value={scenarioForm.period_value} onChange={(e) => setScenarioForm({ ...scenarioForm, period_value: e.target.value })} /></label><label><span className="label">{r("Unit", "واحد")}</span><select className="field" value={scenarioForm.period_unit} onChange={(e) => setScenarioForm({ ...scenarioForm, period_unit: e.target.value as PeriodUnit })}><option value="days">days</option><option value="months">months</option><option value="years">years</option></select></label></div>
        <div className="grid grid-cols-2 gap-2"><label><span className="label">{r("Extension/tolling assumption", "فرض تمدید/tolling")}</span><input type="number" min="0" className="field" dir="ltr" value={scenarioForm.extension_value} onChange={(e) => setScenarioForm({ ...scenarioForm, extension_value: e.target.value })} /></label><label><span className="label">{r("Unit", "واحد")}</span><select className="field" value={scenarioForm.extension_unit} onChange={(e) => setScenarioForm({ ...scenarioForm, extension_unit: e.target.value as PeriodUnit })}><option value="days">days</option><option value="months">months</option><option value="years">years</option></select></label></div>
        <label><span className="label">{r("Extension/tolling basis", "مبنای تمدید/tolling")}</span><input className="field" value={scenarioForm.extension_basis} onChange={(e) => setScenarioForm({ ...scenarioForm, extension_basis: e.target.value })} /></label>
        <label className="md:col-span-2"><span className="label">{r("Assumptions and uncertainty", "فرضیات و عدم قطعیت")}</span><textarea className="field min-h-24" value={scenarioForm.assumptions} onChange={(e) => setScenarioForm({ ...scenarioForm, assumptions: e.target.value })} /></label>
      </div>
      <div className="mt-4 flex gap-2"><button disabled={busy} className="primary-button" onClick={saveScenario}>{busy ? r("Working…", "در حال انجام…") : scenarioEdit ? r("Create new immutable version", "ایجاد نسخه تغییرناپذیر جدید") : r("Compute candidate & save", "محاسبه تاریخ پیشنهادی و ذخیره")}</button>{scenarioEdit ? <button className="secondary-button" onClick={() => { setScenarioEdit(null); setScenarioForm(emptyScenario); }}>{r("Cancel revision", "لغو اصلاح")}</button> : null}</div>
    </section>

    {reviewScenario ? <section className="panel mt-6 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">{r("Manager/Admin human/legal review", "بازبینی انسانی/حقوقی مدیر")}</p><h2 className="mt-1 text-xl font-semibold text-slate-950" dir="auto">{reviewScenario.title}</h2></div><button className="secondary-button" onClick={() => setReviewScenario(null)}>{r("Close", "بستن")}</button></div>
      <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4"><p className="detail-label">{r("Computed candidate — not authoritative", "تاریخ محاسبه‌شده — غیرمعتبر تا تأیید")}</p><p className="mt-1 text-xl font-semibold text-cyan-950" dir="ltr">{formatDate(reviewScenario.candidate_deadline)}</p></div>
      <div className="mt-4 grid gap-3 md:grid-cols-2"><label><span className="label">{r("Review action", "اقدام بازبینی")}</span><select className="field" value={reviewAction} onChange={(e) => setReviewAction(e.target.value as ScenarioReviewAction)}><option value="confirm">{r("Confirm candidate after human/legal review", "تأیید تاریخ پیشنهادی پس از بازبینی")}</option><option value="override">{r("Override with separately verified date", "تغییر با تاریخ جداگانه تأییدشده")}</option><option value="review_needed">{r("Further review needed", "نیاز به بازبینی بیشتر")}</option><option value="reject">{r("Reject this scenario", "رد این سناریو")}</option></select></label>{reviewAction === "override" ? <label><span className="label">{r("Human-confirmed override deadline", "مهلت Override تأییدشده توسط انسان")}</span><input type="date" className="field" dir="ltr" value={overrideDate} onChange={(e) => setOverrideDate(e.target.value)} /></label> : null}</div>
      {reviewAction === "override" ? <label className="mt-3 block"><span className="label">{r("Override source reference", "مرجع منبع Override")}</span><input className="field" value={reviewSource} onChange={(e) => setReviewSource(e.target.value)} /></label> : null}
      <label className="mt-3 block"><span className="label">{r("Human/legal review note", "یادداشت بازبینی انسانی/حقوقی")}</span><textarea className="field min-h-24" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} /></label>
      <button disabled={busy || reviewScenario.source_state_status === "stale" || reviewScenario.source_state_status === "source_unavailable"} className="primary-button mt-4" onClick={submitReview}>{r("Record append-only human review", "ثبت بازبینی انسانی تغییرناپذیر")}</button>
    </section> : null}
  </div>;
}
