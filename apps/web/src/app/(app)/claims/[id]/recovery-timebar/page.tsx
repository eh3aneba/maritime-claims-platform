"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim } from "@/lib/api";
import { formatDate } from "@/lib/format";
import {
  decisionActionLabel,
  evaluationKindLabel,
  reviewT,
  supportStatusLabel,
  urgencyLabel,
} from "@/lib/i18n-review-support";
import type { Claim } from "@/lib/types";
import {
  buildRecoveryTimebar,
  decideRecoveryTimebar,
  getRecoveryTimebar,
  type RecoveryTimebarDecisionAction,
  type RecoveryTimebarEvaluation,
  type RecoveryTimebarSnapshot,
} from "@/lib/recovery-timebar-api";

function statusTone(status: string) {
  if (status === "triggered") return "bg-cyan-50 text-cyan-800 ring-cyan-200";
  if (status === "insufficient_evidence") return "bg-amber-50 text-amber-800 ring-amber-200";
  if (status === "not_applicable") return "bg-slate-50 text-slate-600 ring-slate-200";
  return "bg-emerald-50 text-emerald-700 ring-emerald-200";
}

function urgencyTone(urgency: string) {
  if (urgency === "critical") return "border-red-300 bg-red-50 text-red-800";
  if (urgency === "high") return "border-orange-300 bg-orange-50 text-orange-800";
  if (urgency === "medium") return "border-amber-300 bg-amber-50 text-amber-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function sourceLabel(source: Record<string, unknown>) {
  const kind = String(source.kind ?? "source").replaceAll("_", " ");
  const id = source.id ? String(source.id) : "";
  const field = source.field_path ? ` · ${String(source.field_path)}` : "";
  const version = source.rule_version ? ` · v${String(source.rule_version)}` : "";
  return `${kind}${field}${version}${id ? ` · ${id.slice(0, 12)}` : ""}`;
}

export default function RecoveryTimebarPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [snapshot, setSnapshot] = useState<RecoveryTimebarSnapshot | null>(null);
  const [disclaimer, setDisclaimer] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [action, setAction] = useState<RecoveryTimebarDecisionAction>("accept");
  const [editedAction, setEditedAction] = useState("");
  const [editedImplication, setEditedImplication] = useState("");
  const [editedDueDate, setEditedDueDate] = useState("");
  const [convertToTask, setConvertToTask] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [claimData, dashboard] = await Promise.all([getClaim(id), getRecoveryTimebar(id)]);
      setClaim(claimData);
      setSnapshot(dashboard.snapshot);
      setDisclaimer(dashboard.disclaimer);
      if (dashboard.snapshot?.evaluations.length && !selectedId) setSelectedId(dashboard.snapshot.evaluations[0].id);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Recovery & time-bar workspace could not be loaded.", "محیط بازیافت و مهلت زمانی بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [id]);

  async function refresh() {
    setBusy(true); setError("");
    try {
      const next = await buildRecoveryTimebar(id);
      setSnapshot(next);
      if (next.evaluations.length) setSelectedId(next.evaluations[0].id);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Recovery & time-bar analysis could not be refreshed.", "تحلیل بازیافت و مهلت زمانی به‌روزرسانی نشد."));
    } finally { setBusy(false); }
  }

  const selected = useMemo(
    () => snapshot?.evaluations.find((row) => row.id === selectedId) ?? snapshot?.evaluations[0] ?? null,
    [snapshot, selectedId],
  );

  function choose(row: RecoveryTimebarEvaluation) {
    setSelectedId(row.id);
    setNote("");
    setAction("accept");
    setEditedAction(row.recommended_action);
    setEditedImplication(row.candidate_implication);
    setEditedDueDate(row.candidate_deadline ?? "");
    setConvertToTask(false);
  }

  async function decide() {
    if (!selected) return;
    if (note.trim().length < 5) { setError(r("Add a short human-review note before recording a decision.", "پیش از ثبت تصمیم، یک یادداشت کوتاه بازبینی انسانی وارد کنید.")); return; }
    setBusy(true); setError("");
    try {
      await decideRecoveryTimebar(id, selected.id, {
        action,
        evaluation_hash: selected.evaluation_hash,
        note: note.trim(),
        edited_candidate_implication: action === "edit" ? editedImplication.trim() : null,
        edited_recommended_action: action === "edit" ? editedAction.trim() : null,
        edited_due_date: action === "edit" && editedDueDate ? editedDueDate : null,
        convert_to_task: convertToTask,
      });
      setNote(""); setConvertToTask(false);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Human decision could not be recorded.", "تصمیم انسانی ثبت نشد."));
    } finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">{r("Loading recovery & time-bar workspace…", "در حال بارگذاری محیط بازیافت و مهلت زمانی…")}</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || r("Claim unavailable.", "پرونده در دسترس نیست.")}</div>;

  const recovery = snapshot?.evaluations.find((row) => row.kind === "recovery") ?? null;
  const timebar = snapshot?.evaluations.find((row) => row.kind === "timebar") ?? null;

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r(`← Back to ${claim.vessel.name}`, `→ بازگشت به ${claim.vessel.name}`)}</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
      <div>
        <p className="eyebrow"><span dir="ltr">{claim.claim_reference}</span> · {r("Recovery & time-bar", "بازیافت و مهلت زمانی")}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Recovery & Time-bar Intelligence", "هوشمندی بازیافت و مهلت زمانی")}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{r("Source-linked investigation and diary support. The workspace preserves evidence lineage and refuses to invent a legal deadline when source wording, trigger date or period evidence is incomplete.", "پشتیبانی تحقیق و diary متصل به منبع. این محیط تبار شواهد را حفظ می‌کند و وقتی متن منبع، تاریخ trigger یا شواهد دوره ناقص باشد، از ساختن مهلت قانونی خودداری می‌کند.")}</p>
      </div>
      <button onClick={refresh} disabled={busy} className="primary-button">{busy ? r("Working…", "در حال انجام…") : snapshot ? r("Refresh analysis", "به‌روزرسانی تحلیل") : r("Build analysis", "ساخت تحلیل")}</button>
    </div>

    <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
      <strong>{r("Human/legal verification required.", "تأیید انسانی/حقوقی الزامی است.")}</strong> <span dir="auto">{disclaimer || r("Any candidate date is a review aid, not a legal conclusion or authoritative time bar.", "هر تاریخ پیشنهادی فقط ابزار بازبینی است و نتیجه حقوقی یا time bar معتبر محسوب نمی‌شود.")}</span>
    </div>
    {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">{error}</div> : null}

    {!snapshot ? <section className="panel mt-6 p-8 text-center"><h2 className="section-title">{r("No recovery/time-bar snapshot yet", "هنوز نسخه بازیافت/مهلت زمانی وجود ندارد")}</h2><p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">{r("Build the analysis after reviewing relevant facts and wording. Incomplete source evidence will remain an explicit evidence gap and will not create a candidate deadline.", "پس از بازبینی واقعیت‌ها و wording مرتبط، تحلیل را بسازید. شواهد ناقص منبع به‌صورت شکاف شواهد باقی می‌مانند و تاریخ پیشنهادی ایجاد نمی‌کنند.")}</p></section> : <>
      <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">{r("Snapshot", "نسخه")}</p><p className="metric-value" dir="ltr">v{snapshot.snapshot_version}</p><p className="mt-1 text-xs text-slate-400">{r("Engine", "موتور قواعد")} <span dir="ltr">{snapshot.engine_version}</span></p></div>
        <div className="panel p-5"><p className="metric-label">{r("Recovery status", "وضعیت بازیافت")}</p><p className="mt-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusTone(recovery?.status ?? "not_applicable")}`}>{supportStatusLabel(locale, recovery?.status ?? "not_applicable")}</span></p></div>
        <div className="panel p-5"><p className="metric-label">{r("Time-bar status", "وضعیت مهلت زمانی")}</p><p className="mt-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusTone(timebar?.status ?? "not_applicable")}`}>{supportStatusLabel(locale, timebar?.status ?? "not_applicable")}</span></p></div>
        <div className="panel p-5"><p className="metric-label">{r("Candidate date", "تاریخ پیشنهادی")}</p><p className="metric-value text-xl" dir="ltr">{timebar?.candidate_deadline ? formatDate(timebar.candidate_deadline) : r("Not calculated", "محاسبه نشده")}</p><p className="mt-1 text-xs text-slate-400">{r("Never authoritative without human/legal verification", "بدون تأیید انسانی/حقوقی هرگز معتبر نیست")}</p></div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,.85fr)_minmax(0,1.15fr)]">
        <section className="panel p-5">
          <h2 className="section-title">{r("Evaluations", "ارزیابی‌ها")}</h2><p className="section-subtitle">{r("Select a source-linked evaluation to inspect its derivation and record a human disposition.", "یک ارزیابی متصل به منبع را انتخاب کنید تا derivation آن را بررسی و تصمیم انسانی ثبت کنید.")}</p>
          <div className="mt-4 space-y-3">{snapshot.evaluations.map((row) => <button key={row.id} onClick={() => choose(row)} className={`w-full rounded-xl border p-4 text-left transition ${selected?.id === row.id ? "border-cyan-400 bg-cyan-50/60" : "border-slate-200 hover:bg-slate-50"}`}>
            <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">{evaluationKindLabel(locale, row.kind)}</p><h3 className="mt-1 text-sm font-semibold text-slate-950" dir="auto">{row.title}</h3></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ring-1 ${statusTone(row.status)}`}>{supportStatusLabel(locale, row.status)}</span></div>
            <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${urgencyTone(row.urgency)}`}>{r("Urgency", "فوریت")}: {urgencyLabel(locale, row.urgency)}{row.days_remaining !== null ? <> · <span dir="ltr">{row.days_remaining}</span> {r("day(s) from evaluation date", "روز از تاریخ ارزیابی")}</> : null}</div>
          </button>)}</div>
        </section>

        {selected ? <section className="panel p-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">{evaluationKindLabel(locale, selected.kind)} · {supportStatusLabel(locale, selected.status)}</p><h2 className="mt-1 text-xl font-semibold text-slate-950" dir="auto">{selected.title}</h2></div><span className={`rounded-full border px-3 py-1 text-xs font-semibold ${urgencyTone(selected.urgency)}`}>{urgencyLabel(locale, selected.urgency)} {r("urgency", "فوریت")}</span></div>

          <dl className="mt-5 grid gap-4 sm:grid-cols-2">
            <div><dt className="detail-label">{r("Potential counterparty", "طرف مقابل احتمالی")}</dt><dd className="detail-value" dir="auto">{selected.counterparty ?? r("Not established", "مشخص نشده")}</dd></div>
            <div><dt className="detail-label">{r("Candidate basis", "مبنای پیشنهادی")}</dt><dd className="detail-value" dir="auto">{selected.candidate_basis ?? r("Not established", "مشخص نشده")}</dd></div>
            {selected.kind === "timebar" ? <><div><dt className="detail-label">{r("Approved trigger date", "تاریخ trigger تأییدشده")}</dt><dd className="detail-value" dir="ltr">{selected.trigger_date ? formatDate(selected.trigger_date) : r("Missing", "مفقود")}</dd></div><div><dt className="detail-label">{r("Reviewed period", "دوره بازبینی‌شده")}</dt><dd className="detail-value" dir="ltr">{selected.period_value && selected.period_unit ? `${selected.period_value} ${selected.period_unit}` : r("Missing", "مفقود")}</dd></div><div><dt className="detail-label">{r("Candidate deadline", "مهلت پیشنهادی")}</dt><dd className="detail-value" dir="ltr">{selected.candidate_deadline ? formatDate(selected.candidate_deadline) : r("Not calculated", "محاسبه نشده")}</dd></div><div><dt className="detail-label">{r("Days remaining", "روزهای باقی‌مانده")}</dt><dd className="detail-value" dir="ltr">{selected.days_remaining ?? "—"}</dd></div></> : null}
          </dl>

          <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="detail-label">{r("Candidate implication", "برداشت پیشنهادی")}</p><p className="mt-2 text-sm leading-6 text-slate-700" dir="auto">{selected.candidate_implication}</p><p className="detail-label mt-4">{r("Recommended human action", "اقدام انسانی پیشنهادی")}</p><p className="mt-2 text-sm leading-6 text-slate-700" dir="auto">{selected.recommended_action}</p></div>
          <div className="mt-4"><p className="detail-label">{r("Rationale", "منطق")}</p><p className="mt-2 text-sm leading-6 text-slate-600" dir="auto">{selected.rationale}</p></div>

          {selected.missing_prerequisites.length ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-amber-800">{r("Missing prerequisites", "پیش‌نیازهای مفقود")}</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900" dir="auto">{selected.missing_prerequisites.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}

          <div className="mt-5"><p className="detail-label">{r("Source lineage", "تبار منبع")}</p><div className="mt-2 space-y-2">{selected.source_refs.length ? selected.source_refs.map((source, index) => <div key={`${selected.id}-source-${index}`} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600"><p className="font-semibold text-slate-700" dir="ltr">{sourceLabel(source)}</p>{source.evaluation_hash ? <p className="mt-1 break-all font-mono text-[10px] text-slate-400" dir="ltr">evaluation {String(source.evaluation_hash)}</p> : null}{source.extraction_id ? <p className="mt-1 break-all font-mono text-[10px] text-slate-400" dir="ltr">extraction {String(source.extraction_id)}</p> : null}</div>) : <p className="text-sm text-slate-400">{r("No material source references for this not-applicable evaluation.", "برای این ارزیابی نامرتبط، منبع بااهمیتی ثبت نشده است.")}</p>}</div></div>

          {selected.latest_decision ? <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-violet-700">{r("Latest human decision", "آخرین تصمیم انسانی")} · <span dir="ltr">#{selected.latest_decision.decision_number}</span></p><p className="mt-2 text-sm font-semibold text-slate-900">{decisionActionLabel(locale, selected.latest_decision.action)}</p><p className="mt-1 text-sm text-slate-600" dir="auto">{selected.latest_decision.note}</p>{selected.latest_decision.converted_task_id ? <p className="mt-2 text-xs font-semibold text-violet-700">{r("Controlled task created", "تسک کنترل‌شده ایجاد شد")}: <span dir="ltr">{selected.latest_decision.converted_task_id}</span></p> : null}</div> : null}

          <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="text-sm font-semibold text-slate-950">{r("Record human disposition", "ثبت تصمیم انسانی")}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{r("The immutable evaluation is not edited. Your decision is stored separately with its evaluation hash.", "ارزیابی تغییرناپذیر ویرایش نمی‌شود. تصمیم شما جداگانه همراه با evaluation hash ذخیره می‌شود.")}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2"><label><span className="label">{r("Decision", "تصمیم")}</span><select className="field" value={action} onChange={(e) => { const next = e.target.value as RecoveryTimebarDecisionAction; setAction(next); if (["dismiss", "not_applicable"].includes(next)) setConvertToTask(false); }}><option value="accept">{r("Accept for human follow-up", "پذیرش برای پیگیری انسانی")}</option><option value="edit">{r("Edit human interpretation/action", "ویرایش برداشت/اقدام انسانی")}</option><option value="dismiss">{r("Dismiss", "رد برای این بازبینی")}</option><option value="not_applicable">{r("Not applicable", "نامرتبط")}</option></select></label>{selected.kind === "timebar" && action === "edit" ? <label><span className="label">{r("Human-reviewed task due date", "موعد تسک بازبینی‌شده توسط انسان")}</span><input type="date" dir="ltr" className="field" value={editedDueDate} onChange={(e) => setEditedDueDate(e.target.value)} /></label> : null}</div>
            {action === "edit" ? <div className="mt-3 grid gap-3"><label><span className="label">{r("Edited candidate implication", "برداشت پیشنهادی ویرایش‌شده")}</span><textarea className="field min-h-24" dir="auto" value={editedImplication} onChange={(e) => setEditedImplication(e.target.value)} /></label><label><span className="label">{r("Edited recommended action", "اقدام پیشنهادی ویرایش‌شده")}</span><textarea className="field min-h-24" dir="auto" value={editedAction} onChange={(e) => setEditedAction(e.target.value)} /></label></div> : null}
            <label className="mt-3 block"><span className="label">{r("Review note", "یادداشت بازبینی")}</span><textarea className="field min-h-24" dir="auto" value={note} onChange={(e) => setNote(e.target.value)} placeholder={r("Explain the human review and source verification performed.", "بازبینی انسانی و تأیید منبع انجام‌شده را توضیح دهید.")} /></label>
            {action === "accept" || action === "edit" ? <label className="mt-3 flex items-start gap-2 rounded-lg border border-slate-200 p-3 text-sm text-slate-700"><input type="checkbox" className="mt-1" checked={convertToTask} onChange={(e) => setConvertToTask(e.target.checked)} /><span><strong>{r("Create controlled task/diary entry after this decision.", "پس از این تصمیم، تسک/diary کنترل‌شده ایجاد شود.")}</strong><br/><span className="text-xs text-slate-500">{r("For a time-bar evaluation, the candidate date (or your edited date) becomes the task due date only through this explicit human action.", "در ارزیابی time-bar، تاریخ پیشنهادی (یا تاریخ ویرایش‌شده شما) فقط از طریق این اقدام صریح انسانی به موعد تسک تبدیل می‌شود.")}</span></span></label> : null}
            <button disabled={busy || note.trim().length < 5} onClick={decide} className="primary-button mt-4">{busy ? r("Recording…", "در حال ثبت…") : r("Record human decision", "ثبت تصمیم انسانی")}</button>
          </div>
        </section> : null}
      </div>
    </>}
  </div>;
}
