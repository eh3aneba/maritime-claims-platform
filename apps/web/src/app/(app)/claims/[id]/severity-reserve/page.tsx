"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim } from "@/lib/api";
import {
  decisionActionLabel,
  evaluationKindLabel,
  reviewT,
  severityLabel,
  supportStatusLabel,
} from "@/lib/i18n-review-support";
import type { Locale } from "@/lib/i18n";
import type { Claim } from "@/lib/types";
import {
  buildSeverityReserve,
  decideSeverityReserve,
  getSeverityReserve,
  type SeverityReserveDecisionAction,
  type SeverityReserveEvaluation,
  type SeverityReserveSnapshot,
} from "@/lib/severity-reserve-api";

function statusTone(status: string) {
  if (status === "triggered") return "bg-cyan-50 text-cyan-800 ring-cyan-200";
  if (status === "insufficient_evidence") return "bg-amber-50 text-amber-800 ring-amber-200";
  if (status === "not_applicable") return "bg-slate-50 text-slate-600 ring-slate-200";
  return "bg-emerald-50 text-emerald-700 ring-emerald-200";
}

function severityTone(value: string | null) {
  if (value === "critical") return "border-rose-300 bg-rose-50 text-rose-900";
  if (value === "high") return "border-orange-300 bg-orange-50 text-orange-900";
  if (value === "medium") return "border-amber-300 bg-amber-50 text-amber-900";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function amount(locale: Locale, value: string | number | null, currency: string | null) {
  if (value === null || value === undefined || !currency) return reviewT(locale, "Not calculated", "محاسبه نشده");
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return `${currency} ${String(value)}`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(parsed);
}

function sourceLabel(source: Record<string, unknown>) {
  const kind = String(source.kind ?? "source").replaceAll("_", " ");
  const id = source.id ? ` · ${String(source.id).slice(0, 12)}` : "";
  const field = source.field_path ? ` · ${String(source.field_path)}` : "";
  return `${kind}${field}${id}`;
}

export default function SeverityReservePage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [snapshot, setSnapshot] = useState<SeverityReserveSnapshot | null>(null);
  const [disclaimer, setDisclaimer] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [action, setAction] = useState<SeverityReserveDecisionAction>("accept");
  const [note, setNote] = useState("");
  const [editedSeverity, setEditedSeverity] = useState<"low" | "medium" | "high" | "critical">("medium");
  const [editedLower, setEditedLower] = useState("");
  const [editedUpper, setEditedUpper] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setError("");
    try {
      const [claimData, dashboard] = await Promise.all([getClaim(id), getSeverityReserve(id)]);
      setClaim(claimData);
      setSnapshot(dashboard.snapshot);
      setDisclaimer(dashboard.disclaimer);
      if (dashboard.snapshot?.evaluations.length && !selectedId) setSelectedId(dashboard.snapshot.evaluations[0].id);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Severity & reserve support workspace could not be loaded.", "محیط پشتیبانی شدت و ذخیره بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [id]);

  async function refresh() {
    setBusy(true); setError(""); setMessage("");
    try {
      const next = await buildSeverityReserve(id);
      setSnapshot(next);
      if (next.evaluations.length) setSelectedId(next.evaluations[0].id);
      setMessage(r(`Support snapshot v${next.snapshot_version} is ready.`, `نسخه پشتیبانی v${next.snapshot_version} آماده است.`));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Severity & reserve support could not be refreshed.", "پشتیبانی شدت و ذخیره به‌روزرسانی نشد."));
    } finally { setBusy(false); }
  }

  const selected = useMemo(
    () => snapshot?.evaluations.find((row) => row.id === selectedId) ?? snapshot?.evaluations[0] ?? null,
    [snapshot, selectedId],
  );

  function choose(row: SeverityReserveEvaluation) {
    setSelectedId(row.id);
    setAction("accept");
    setNote("");
    setEditedSeverity(row.severity_label ?? "medium");
    setEditedLower(row.lower_amount === null ? "" : String(row.lower_amount));
    setEditedUpper(row.upper_amount === null ? "" : String(row.upper_amount));
  }

  async function decide() {
    if (!selected) return;
    if (note.trim().length < 5) { setError(r("Add a short human-review note before recording a decision.", "پیش از ثبت تصمیم، یک یادداشت کوتاه بازبینی انسانی وارد کنید.")); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      await decideSeverityReserve(id, selected.id, {
        action,
        evaluation_hash: selected.evaluation_hash,
        note: note.trim(),
        edited_severity_label: action === "edit" && selected.kind === "severity" ? editedSeverity : null,
        edited_lower_amount: action === "edit" && selected.kind === "reserve" && editedLower ? editedLower : null,
        edited_upper_amount: action === "edit" && selected.kind === "reserve" && editedUpper ? editedUpper : null,
      });
      setMessage(r("Human disposition recorded. Authoritative reserve state was not changed.", "تصمیم انسانی ثبت شد. وضعیت ذخیره معتبر تغییر نکرد."));
      setNote("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Human disposition could not be recorded.", "تصمیم انسانی ثبت نشد."));
    } finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">{r("Loading severity & reserve support…", "در حال بارگذاری پشتیبانی شدت و ذخیره…")}</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || r("Claim unavailable.", "پرونده در دسترس نیست.")}</div>;

  const severity = snapshot?.evaluations.find((row) => row.kind === "severity") ?? null;
  const reserve = snapshot?.evaluations.find((row) => row.kind === "reserve") ?? null;

  return <div className="space-y-6">
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r(`← Back to ${claim.vessel.name}`, `→ بازگشت به ${claim.vessel.name}`)}</Link>
    <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
      <div>
        <p className="eyebrow"><span dir="ltr">{claim.claim_reference} · Phase 12D</span></p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Severity & Reserve Support", "پشتیبانی شدت و ذخیره")}</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">{r("Explainable handling-priority and reserve-range review support from current source-linked evidence. No FX rate, reserve, policy amount or future cost is invented.", "پشتیبانی قابل توضیح برای اولویت رسیدگی و بازبینی بازه ذخیره، بر مبنای شواهد فعلی متصل به منبع. هیچ نرخ FX، ذخیره، مبلغ بیمه‌نامه یا هزینه آینده‌ای ساخته یا حدس زده نمی‌شود.")}</p>
      </div>
      <button onClick={refresh} disabled={busy} className="primary-button disabled:opacity-40">{busy ? r("Working…", "در حال انجام…") : snapshot ? r("Refresh support", "به‌روزرسانی پشتیبانی") : r("Build support", "ساخت پشتیبانی")}</button>
    </div>

    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
      <strong>{r("Human reserve authority required.", "اختیار انسانی برای ذخیره الزامی است.")}</strong> <span dir="auto">{disclaimer || r("This workspace never creates or changes an authoritative reserve.", "این محیط هرگز ذخیره معتبر ایجاد یا تغییر نمی‌دهد.")}</span>
    </div>
    {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">{error}</div> : null}
    {message ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</div> : null}

    {!snapshot ? <section className="panel p-8 text-center"><h2 className="section-title">{r("No support snapshot yet", "هنوز نسخه پشتیبانی وجود ندارد")}</h2><p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">{r("Build support after financial evidence and claim facts have been human-reviewed. Missing or mixed-currency evidence remains explicit and does not create a guessed range.", "پس از بازبینی انسانی شواهد مالی و واقعیت‌های پرونده، پشتیبانی را بسازید. شواهد مفقود یا چندارزی صریح باقی می‌مانند و باعث ایجاد بازه حدسی نمی‌شوند.")}</p></section> : <>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">{r("Snapshot", "نسخه")}</p><p className="metric-value" dir="ltr">v{snapshot.snapshot_version}</p><p className="mt-1 text-xs text-slate-400"><span>{r("Engine", "موتور قواعد")}</span> <span dir="ltr">{snapshot.engine_version}</span></p></div>
        <div className={`rounded-xl border p-5 ${severityTone(severity?.severity_label ?? null)}`}><p className="metric-label">{r("Handling severity", "شدت رسیدگی")}</p><p className="mt-2 text-2xl font-semibold">{severityLabel(locale, severity?.severity_label)}</p><p className="mt-1 text-xs"><span dir="ltr">{r("Score", "امتیاز")} {severity?.severity_score ?? 0}</span> · {r("workflow priority only", "فقط اولویت گردش کار")}</p></div>
        <div className="panel p-5"><p className="metric-label">{r("Reserve support", "پشتیبانی ذخیره")}</p><p className="mt-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusTone(reserve?.status ?? "not_applicable")}`}>{supportStatusLabel(locale, reserve?.status ?? "not_applicable")}</span></p></div>
        <div className="panel p-5"><p className="metric-label">{r("Candidate range", "بازه پیشنهادی")}</p><p className="mt-2 text-sm font-semibold text-slate-950" dir="ltr">{reserve?.status === "triggered" ? `${amount(locale, reserve.lower_amount, reserve.currency)} – ${amount(locale, reserve.upper_amount, reserve.currency)}` : r("Not calculated", "محاسبه نشده")}</p><p className="mt-1 text-xs text-slate-400">{r("Never writes ReserveHistory", "هرگز در ReserveHistory ثبت نمی‌کند")}</p></div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)]">
        <section className="panel p-5">
          <h2 className="section-title">{r("Evaluations", "ارزیابی‌ها")}</h2><p className="section-subtitle">{r("Select an immutable evaluation to inspect factors, evidence gaps and human disposition.", "یک ارزیابی تغییرناپذیر را انتخاب کنید تا عوامل، شکاف‌های شواهد و تصمیم انسانی را بررسی کنید.")}</p>
          <div className="mt-4 space-y-3">{snapshot.evaluations.map((row) => <button key={row.id} onClick={() => choose(row)} className={`w-full rounded-xl border p-4 text-left transition ${selected?.id === row.id ? "border-cyan-400 bg-cyan-50/60" : "border-slate-200 hover:bg-slate-50"}`}>
            <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">{evaluationKindLabel(locale, row.kind)}</p><h3 className="mt-1 text-sm font-semibold text-slate-950" dir="auto">{row.title}</h3></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ring-1 ${statusTone(row.status)}`}>{supportStatusLabel(locale, row.status)}</span></div>
            {row.kind === "severity" ? <p className="mt-3 text-xs font-semibold text-slate-600">{severityLabel(locale, row.severity_label)} · <span dir="ltr">{r("score", "امتیاز")} {row.severity_score}</span></p> : <p className="mt-3 text-xs font-semibold text-slate-600" dir="ltr">{row.status === "triggered" ? `${amount(locale, row.lower_amount, row.currency)} – ${amount(locale, row.upper_amount, row.currency)}` : r("No evidence-grounded range", "بازه مبتنی بر شواهد وجود ندارد")}</p>}
          </button>)}</div>
        </section>

        {selected ? <section className="panel p-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">{evaluationKindLabel(locale, selected.kind)} · {supportStatusLabel(locale, selected.status)}</p><h2 className="mt-1 text-xl font-semibold text-slate-950" dir="auto">{selected.title}</h2></div>{selected.kind === "severity" ? <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${severityTone(selected.severity_label)}`}>{severityLabel(locale, selected.severity_label)} · <span dir="ltr">{selected.severity_score}</span></span> : null}</div>

          {selected.kind === "reserve" ? <dl className="mt-5 grid gap-4 sm:grid-cols-3"><div><dt className="detail-label">{r("Currency", "ارز")}</dt><dd className="detail-value" dir="ltr">{selected.currency ?? "—"}</dd></div><div><dt className="detail-label">{r("Observed floor", "کف مشاهده‌شده")}</dt><dd className="detail-value" dir="ltr">{amount(locale, selected.lower_amount, selected.currency)}</dd></div><div><dt className="detail-label">{r("Upper evidence point", "نقطه بالای شواهد")}</dt><dd className="detail-value" dir="ltr">{amount(locale, selected.upper_amount, selected.currency)}</dd></div></dl> : null}

          <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="detail-label">{r("Candidate implication", "برداشت پیشنهادی")}</p><p className="mt-2 text-sm leading-6 text-slate-700" dir="auto">{selected.candidate_implication}</p><p className="detail-label mt-4">{r("Recommended human action", "اقدام انسانی پیشنهادی")}</p><p className="mt-2 text-sm leading-6 text-slate-700" dir="auto">{selected.recommended_action}</p></div>
          <div className="mt-4"><p className="detail-label">{r("Rationale", "منطق")}</p><p className="mt-2 text-sm leading-6 text-slate-600" dir="auto">{selected.rationale}</p></div>

          <div className="mt-5"><p className="detail-label">{r("Explainable factors", "عوامل قابل توضیح")}</p><div className="mt-2 space-y-2">{selected.factors.map((factor, index) => <div key={index} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600" dir="ltr">{JSON.stringify(factor)}</div>)}</div></div>
          {selected.missing_prerequisites.length ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-amber-800">{r("Evidence / currency gaps", "شکاف‌های شواهد / ارز")}</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900" dir="auto">{selected.missing_prerequisites.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}

          <div className="mt-5"><p className="detail-label">{r("Source lineage", "تبار منبع")}</p><div className="mt-2 space-y-2">{selected.source_refs.length ? selected.source_refs.map((source, index) => <div key={index} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600"><p className="font-semibold text-slate-700" dir="ltr">{sourceLabel(source)}</p><pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[10px] text-slate-400" dir="ltr">{JSON.stringify(source)}</pre></div>) : <p className="text-sm text-slate-400">{r("No material monetary source is available for this evidence-gap evaluation.", "برای این ارزیابی شکاف شواهد، منبع مالی بااهمیتی موجود نیست.")}</p>}</div></div>

          {selected.latest_decision ? <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-violet-700">{r("Latest human decision", "آخرین تصمیم انسانی")} · <span dir="ltr">#{selected.latest_decision.decision_number}</span></p><p className="mt-2 text-sm font-semibold text-slate-900">{decisionActionLabel(locale, selected.latest_decision.action)}</p><p className="mt-1 text-sm text-slate-600" dir="auto">{selected.latest_decision.note}</p></div> : null}

          <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="text-sm font-semibold text-slate-950">{r("Record human disposition", "ثبت تصمیم انسانی")}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{r("The immutable support output is not edited. This decision is append-only and does not update the authoritative reserve.", "خروجی پشتیبانی تغییرناپذیر ویرایش نمی‌شود. این تصمیم فقط به‌صورت append-only ثبت می‌شود و ذخیره معتبر را به‌روزرسانی نمی‌کند.")}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2"><label><span className="label">{r("Decision", "تصمیم")}</span><select className="field" value={action} onChange={(e) => setAction(e.target.value as SeverityReserveDecisionAction)}><option value="accept">{r("Accept as review support", "پذیرش به‌عنوان پشتیبانی بازبینی")}</option><option value="edit">{r("Edit human interpretation", "ویرایش برداشت انسانی")}</option><option value="dismiss">{r("Dismiss", "رد برای این بازبینی")}</option><option value="not_applicable">{r("Not applicable", "نامرتبط")}</option></select></label>{action === "edit" && selected.kind === "severity" ? <label><span className="label">{r("Human severity", "شدت تعیین‌شده توسط انسان")}</span><select className="field" value={editedSeverity} onChange={(e) => setEditedSeverity(e.target.value as typeof editedSeverity)}><option value="low">{severityLabel(locale, "low")}</option><option value="medium">{severityLabel(locale, "medium")}</option><option value="high">{severityLabel(locale, "high")}</option><option value="critical">{severityLabel(locale, "critical")}</option></select></label> : null}</div>
            {action === "edit" && selected.kind === "reserve" ? <div className="mt-3 grid gap-3 sm:grid-cols-2"><label><span className="label">{r("Human lower amount", "مبلغ پایین تعیین‌شده توسط انسان")}</span><input className="field" dir="ltr" type="number" min="0" value={editedLower} onChange={(e) => setEditedLower(e.target.value)} /></label><label><span className="label">{r("Human upper amount", "مبلغ بالای تعیین‌شده توسط انسان")}</span><input className="field" dir="ltr" type="number" min="0" value={editedUpper} onChange={(e) => setEditedUpper(e.target.value)} /></label></div> : null}
            <label className="mt-3 block"><span className="label">{r("Human review note", "یادداشت بازبینی انسانی")}</span><textarea className="field min-h-24" dir="auto" value={note} onChange={(e) => setNote(e.target.value)} placeholder={r("Record why this support output is accepted, edited, dismissed or not applicable.", "توضیح دهید چرا این خروجی پشتیبانی پذیرفته، ویرایش، رد یا نامرتبط تشخیص داده شده است.")} /></label>
            <button onClick={decide} disabled={busy} className="primary-button mt-4 disabled:opacity-40">{r("Record human disposition", "ثبت تصمیم انسانی")}</button>
            <p className="mt-3 text-xs font-semibold text-rose-700">{r("There is deliberately no “Set reserve automatically” action in this workspace.", "عمداً هیچ اقدام «تنظیم خودکار ذخیره» در این محیط وجود ندارد.")}</p>
          </div>
        </section> : null}
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 text-[11px] text-slate-500"><p><span>{r("Engine", "موتور قواعد")}</span> <span dir="ltr">{snapshot.engine_version}</span> · {r("generated", "تولیدشده")} <span dir="ltr">{new Date(snapshot.generated_at).toLocaleString("en-US")}</span></p><p className="mt-1 break-all font-mono" dir="ltr">Source-state SHA-256: {snapshot.source_state_hash}</p><p className="mt-1 break-all font-mono" dir="ltr">Snapshot SHA-256: {snapshot.snapshot_hash}</p></section>
    </>}
  </div>;
}
