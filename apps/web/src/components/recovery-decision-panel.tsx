"use client";

import { useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { reviewT } from "@/lib/i18n-review-support";
import {
  appendRecoveryAction,
  createRecoveryPursuitDecision,
  getRecoveryDecisionDashboard,
  reviseRecoveryPursuitDecision,
  type RecoveryActionDirection,
  type RecoveryActionType,
  type RecoveryDecisionDashboard,
  type RecoveryDisposition,
  type RecoveryPursuitDecision,
} from "@/lib/recovery-decision-api";
import { getRecoveryMaturity, type RecoveryCounterparty } from "@/lib/recovery-timebar-api";

const emptyDecision = {
  counterparty_id: "",
  disposition: "monitor" as RecoveryDisposition,
  rationale: "",
  basis_reference: "",
  next_review_date: "",
};

const emptyAction = {
  action_type: "correspondence" as RecoveryActionType,
  direction: "outbound" as RecoveryActionDirection,
  occurred_on: "",
  summary: "",
  source_reference: "",
  external_status: "",
  external_response_date: "",
};

function contextTone(status: string) {
  if (status === "current") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "reference_only") return "border-slate-200 bg-slate-50 text-slate-700";
  return "border-amber-300 bg-amber-50 text-amber-900";
}

export default function RecoveryDecisionPanel({ claimId }: { claimId: string }) {
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [dashboard, setDashboard] = useState<RecoveryDecisionDashboard | null>(null);
  const [counterparties, setCounterparties] = useState<RecoveryCounterparty[]>([]);
  const [decisionForm, setDecisionForm] = useState(emptyDecision);
  const [decisionEdit, setDecisionEdit] = useState<RecoveryPursuitDecision | null>(null);
  const [actionDecision, setActionDecision] = useState<RecoveryPursuitDecision | null>(null);
  const [actionForm, setActionForm] = useState(emptyAction);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [decisionData, maturity] = await Promise.all([
        getRecoveryDecisionDashboard(claimId),
        getRecoveryMaturity(claimId),
      ]);
      setDashboard(decisionData);
      setCounterparties(maturity.counterparties);
      if (actionDecision) {
        setActionDecision(decisionData.decisions.find((row) => row.decision_key === actionDecision.decision_key) ?? null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Recovery decisions could not be loaded.", "تصمیم‌های بازیافت بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [claimId]);

  function editDecision(row: RecoveryPursuitDecision) {
    setDecisionEdit(row);
    const currentCounterparty = counterparties.some((item) => item.id === row.counterparty_id)
      ? row.counterparty_id
      : "";
    setDecisionForm({
      counterparty_id: currentCounterparty,
      disposition: row.disposition,
      rationale: row.rationale,
      basis_reference: row.basis_reference,
      next_review_date: row.next_review_date ?? "",
    });
  }

  async function saveDecision() {
    if (!decisionForm.counterparty_id || decisionForm.rationale.trim().length < 5 || decisionForm.basis_reference.trim().length < 3) {
      setError(r("Select the current counterparty and complete the rationale and basis reference.", "طرف فعلی را انتخاب و دلیل و مرجع تصمیم را کامل کنید."));
      return;
    }
    setBusy(true); setError("");
    const payload = {
      counterparty_id: decisionForm.counterparty_id,
      disposition: decisionForm.disposition,
      rationale: decisionForm.rationale.trim(),
      basis_reference: decisionForm.basis_reference.trim(),
      next_review_date: decisionForm.next_review_date || null,
    };
    try {
      if (decisionEdit) {
        await reviseRecoveryPursuitDecision(claimId, decisionEdit.decision_key, {
          ...payload,
          expected_decision_hash: decisionEdit.decision_hash,
        });
      } else {
        await createRecoveryPursuitDecision(claimId, payload);
      }
      setDecisionEdit(null);
      setDecisionForm(emptyDecision);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Recovery decision could not be saved.", "تصمیم بازیافت ذخیره نشد."));
    } finally {
      setBusy(false);
    }
  }

  async function saveAction() {
    if (!actionDecision || !actionForm.occurred_on || actionForm.summary.trim().length < 3 || actionForm.source_reference.trim().length < 3) {
      setError(r("Complete the action date, summary and source reference.", "تاریخ اقدام، خلاصه و مرجع منبع را کامل کنید."));
      return;
    }
    setBusy(true); setError("");
    try {
      await appendRecoveryAction(claimId, actionDecision.decision_key, {
        decision_hash: actionDecision.decision_hash,
        action_type: actionForm.action_type,
        direction: actionForm.direction,
        occurred_on: actionForm.occurred_on,
        summary: actionForm.summary.trim(),
        source_reference: actionForm.source_reference.trim(),
        external_status: actionForm.external_status.trim() || null,
        external_response_date: actionForm.external_response_date || null,
      });
      setActionForm(emptyAction);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Recovery action could not be recorded.", "اقدام بازیافت ثبت نشد."));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <section className="panel mt-6 p-5 text-sm text-slate-500">{r("Loading recovery decision lineage…", "در حال بارگذاری زنجیره تصمیم بازیافت…")}</section>;
  }
  if (!dashboard) {
    return <section className="panel mt-6 p-5 text-sm text-red-700">{error || r("Recovery decisions unavailable.", "تصمیم‌های بازیافت در دسترس نیست.")}</section>;
  }

  return <section className="panel mt-6 p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="eyebrow">{r("Human recovery authority", "اختیار انسانی بازیافت")}</p>
        <h2 className="section-title mt-1">{r("Recovery decision & action lineage", "زنجیره تصمیم و اقدامات بازیافت")}</h2>
        <p className="section-subtitle">{r("Record pursue / monitor / do-not-pursue / close decisions and the correspondence/actions that follow. The platform records your decision; it does not make it.", "تصمیم‌های پیگیری، پایش، عدم پیگیری یا بستن و مکاتبات/اقدامات بعدی را ثبت کنید. سیستم تصمیم شما را ثبت می‌کند؛ تصمیم را نمی‌گیرد.")}</p>
      </div>
    </div>

    <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-900" dir="auto">
      <strong>{r("Human decision only.", "فقط تصمیم انسانی.")}</strong> {dashboard.disclaimer}
    </div>
    {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">{error}</div> : null}

    <div className="mt-5 space-y-3">
      {dashboard.decisions.length ? dashboard.decisions.map((row) => <div key={row.id} className="rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950" dir="auto">{row.counterparty_name}</h3>
            <p className="mt-1 text-xs text-slate-500" dir="auto">{row.counterparty_role} · v{row.version}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-800">{row.disposition.replaceAll("_", " ")}</span>
            <span className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${contextTone(row.context_state_status)}`}>{row.context_state_status.replaceAll("_", " ")}</span>
          </div>
        </div>
        <p className="mt-3 text-sm leading-6 text-slate-600" dir="auto">{row.rationale}</p>
        <p className="mt-2 text-xs text-slate-400" dir="auto">{r("Basis", "مبنا")}: {row.basis_reference}</p>
        {row.next_review_date ? <p className="mt-2 text-xs text-slate-500">{r("Next human review", "بازبینی انسانی بعدی")}: <span dir="ltr">{formatDate(row.next_review_date)}</span></p> : null}

        {row.actions.length ? <div className="mt-4 border-t border-slate-100 pt-3">
          <p className="detail-label">{r("Recent append-only actions", "اقدامات تغییرناپذیر اخیر")}</p>
          <div className="mt-2 space-y-2">{row.actions.slice(0, 4).map((action) => <div key={action.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <div className="flex flex-wrap justify-between gap-2"><strong>#{action.action_number} · {action.action_type.replaceAll("_", " ")} · {action.direction}</strong><span dir="ltr">{formatDate(action.occurred_on)}</span></div>
            <p className="mt-1" dir="auto">{action.summary}</p>
            {action.external_status ? <p className="mt-1 text-slate-500" dir="auto">{r("External status", "وضعیت خارجی")}: {action.external_status}</p> : null}
          </div>)}</div>
        </div> : null}

        <div className="mt-4 flex flex-wrap gap-2">
          <button className="secondary-button" onClick={() => editDecision(row)}>{r("Create revised decision", "ایجاد نسخه اصلاح‌شده تصمیم")}</button>
          <button
            disabled={row.context_state_status === "stale" || row.context_state_status === "source_unavailable"}
            className="secondary-button"
            onClick={() => { setActionDecision(row); setActionForm(emptyAction); }}
          >{r("Add action / correspondence", "افزودن اقدام / مکاتبه")}</button>
        </div>
      </div>) : <p className="text-sm text-slate-400">{r("No human recovery decision paths yet.", "هنوز مسیر تصمیم انسانی بازیافت ثبت نشده است.")}</p>}
    </div>

    <div className="mt-6 border-t border-slate-200 pt-5">
      <h3 className="text-sm font-semibold text-slate-950">{decisionEdit ? r("Revise recovery decision", "اصلاح تصمیم بازیافت") : r("Record recovery decision", "ثبت تصمیم بازیافت")}</h3>
      {decisionEdit?.context_state_status === "stale" ? <p className="mt-2 text-xs leading-5 text-amber-700">{r("The prior decision is stale because its counterparty/source context evolved. Select the current version of the same logical counterparty and record a deliberate new decision version.", "تصمیم قبلی به‌دلیل تغییر زمینه طرف مقابل/منبع stale شده است. نسخه فعلی همان طرف منطقی را انتخاب و نسخه جدید تصمیم را آگاهانه ثبت کنید.")}</p> : null}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label><span className="label">{r("Current counterparty version", "نسخه فعلی طرف مقابل")}</span><select className="field" value={decisionForm.counterparty_id} onChange={(e) => setDecisionForm({ ...decisionForm, counterparty_id: e.target.value })}><option value="">{r("Select counterparty", "انتخاب طرف مقابل")}</option>{counterparties.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.role} · v{row.version}</option>)}</select></label>
        <label><span className="label">{r("Human disposition", "تصمیم انسانی")}</span><select className="field" value={decisionForm.disposition} onChange={(e) => setDecisionForm({ ...decisionForm, disposition: e.target.value as RecoveryDisposition })}><option value="pursue">{r("Pursue", "پیگیری")}</option><option value="monitor">{r("Monitor", "پایش")}</option><option value="do_not_pursue">{r("Do not pursue", "عدم پیگیری")}</option><option value="close">{r("Close recovery path", "بستن مسیر بازیافت")}</option></select></label>
        <label className="md:col-span-2"><span className="label">{r("Human rationale", "دلیل انسانی")}</span><textarea className="field min-h-24" value={decisionForm.rationale} onChange={(e) => setDecisionForm({ ...decisionForm, rationale: e.target.value })} /></label>
        <label><span className="label">{r("Basis / source reference", "مرجع مبنا / منبع")}</span><input className="field" value={decisionForm.basis_reference} onChange={(e) => setDecisionForm({ ...decisionForm, basis_reference: e.target.value })} /></label>
        <label><span className="label">{r("Next human review date (optional)", "تاریخ بازبینی انسانی بعدی (اختیاری)")}</span><input type="date" className="field" dir="ltr" value={decisionForm.next_review_date} onChange={(e) => setDecisionForm({ ...decisionForm, next_review_date: e.target.value })} /></label>
      </div>
      <div className="mt-4 flex gap-2"><button disabled={busy} className="primary-button" onClick={saveDecision}>{busy ? r("Working…", "در حال انجام…") : decisionEdit ? r("Create immutable decision version", "ایجاد نسخه تغییرناپذیر تصمیم") : r("Record human decision", "ثبت تصمیم انسانی")}</button>{decisionEdit ? <button className="secondary-button" onClick={() => { setDecisionEdit(null); setDecisionForm(emptyDecision); }}>{r("Cancel revision", "لغو اصلاح")}</button> : null}</div>
    </div>

    {actionDecision ? <div className="mt-6 border-t border-slate-200 pt-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">{r("Append-only action log", "دفتر اقدامات تغییرناپذیر")}</p><h3 className="mt-1 text-lg font-semibold text-slate-950" dir="auto">{actionDecision.counterparty_name}</h3></div><button className="secondary-button" onClick={() => setActionDecision(null)}>{r("Close", "بستن")}</button></div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <label><span className="label">{r("Action type", "نوع اقدام")}</span><select className="field" value={actionForm.action_type} onChange={(e) => setActionForm({ ...actionForm, action_type: e.target.value as RecoveryActionType })}><option value="correspondence">{r("Correspondence", "مکاتبه")}</option><option value="demand">{r("Human-approved demand record", "ثبت مطالبه تأییدشده انسانی")}</option><option value="follow_up">{r("Follow-up", "پیگیری")}</option><option value="response">{r("External response", "پاسخ خارجی")}</option><option value="note">{r("Internal note", "یادداشت داخلی")}</option></select></label>
        <label><span className="label">{r("Direction", "جهت")}</span><select className="field" value={actionForm.direction} onChange={(e) => setActionForm({ ...actionForm, direction: e.target.value as RecoveryActionDirection })}><option value="outbound">{r("Outbound", "خروجی")}</option><option value="inbound">{r("Inbound", "ورودی")}</option><option value="internal">{r("Internal", "داخلی")}</option></select></label>
        <label><span className="label">{r("Occurred on", "تاریخ وقوع")}</span><input type="date" className="field" dir="ltr" value={actionForm.occurred_on} onChange={(e) => setActionForm({ ...actionForm, occurred_on: e.target.value })} /></label>
        <label className="md:col-span-3"><span className="label">{r("Human-entered summary", "خلاصه واردشده توسط انسان")}</span><textarea className="field min-h-24" value={actionForm.summary} onChange={(e) => setActionForm({ ...actionForm, summary: e.target.value })} /></label>
        <label><span className="label">{r("Source reference", "مرجع منبع")}</span><input className="field" value={actionForm.source_reference} onChange={(e) => setActionForm({ ...actionForm, source_reference: e.target.value })} /></label>
        <label><span className="label">{r("Externally supplied status (optional)", "وضعیت اعلام‌شده خارجی (اختیاری)")}</span><input className="field" value={actionForm.external_status} onChange={(e) => setActionForm({ ...actionForm, external_status: e.target.value })} /></label>
        <label><span className="label">{r("External response date (optional)", "تاریخ پاسخ خارجی (اختیاری)")}</span><input type="date" className="field" dir="ltr" value={actionForm.external_response_date} onChange={(e) => setActionForm({ ...actionForm, external_response_date: e.target.value })} /></label>
      </div>
      <button disabled={busy || actionDecision.context_state_status === "stale" || actionDecision.context_state_status === "source_unavailable"} className="primary-button mt-4" onClick={saveAction}>{r("Append human action", "افزودن اقدام انسانی")}</button>
    </div> : null}
  </section>;
}
