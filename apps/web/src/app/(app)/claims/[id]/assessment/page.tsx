"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, approveInitialAssessment, generateInitialAssessment, getClaim, getInitialAssessment, reviewAssessmentSection } from "@/lib/api";
import type { Claim, InitialAssessment } from "@/lib/types";

export default function InitialAssessmentPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [assessment, setAssessment] = useState<InitialAssessment | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [overrideReason, setOverrideReason] = useState("Preliminary assessment required while outstanding evidence is being obtained.");
  const [editing, setEditing] = useState<Record<string, string>>({});

  async function load() {
    try { const [c, a] = await Promise.all([getClaim(id), getInitialAssessment(id)]); setClaim(c); setAssessment(a); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Assessment could not be loaded."); }
  }
  useEffect(() => { load(); }, [id]);

  async function generate(allow: boolean) {
    setBusy(true); setError("");
    try { setAssessment(await generateInitialAssessment(id, { allow_if_not_ready: allow, override_reason: allow ? overrideReason : null })); }
    catch (e) {
      if (e instanceof ApiError && e.status === 409) setError("Assessment is not ready. Review the blocking evidence below or generate a preliminary draft with an explicit reason.");
      else setError(e instanceof ApiError ? e.detail : "Assessment could not be generated.");
    } finally { setBusy(false); }
  }

  async function review(sectionId: string, action: "approve" | "edit") {
    if (!assessment) return;
    setBusy(true); setError("");
    try {
      const updated = await reviewAssessmentSection(id, sectionId, { action, text: action === "edit" ? editing[sectionId] : null });
      setAssessment({ ...assessment, status: assessment.status === "draft" ? "under_review" : assessment.status, sections: assessment.sections.map((s) => s.id === updated.id ? updated : s) });
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Section review failed."); }
    finally { setBusy(false); }
  }

  async function approveAll() {
    if (!assessment) return;
    setBusy(true); setError("");
    try { setAssessment(await approveInitialAssessment(id, assessment.id, assessment.is_preliminary ? "Approved as preliminary assessment subject to outstanding evidence." : "Initial assessment reviewed.")); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Assessment could not be approved. Manager access may be required."); }
    finally { setBusy(false); }
  }

  if (!claim) return <div className="py-20 text-center text-sm text-slate-500">Loading assessment…</div>;

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claim</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
      <div><p className="eyebrow">{claim.claim_reference}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Initial Assessment</h1><p className="mt-2 text-sm text-slate-500">Source-linked structured assessment with section-by-section human approval.</p></div>
      <div className="flex gap-2"><button disabled={busy} onClick={() => generate(false)} className="secondary-button">Generate draft</button>{assessment ? <button disabled={busy || assessment.status === "approved"} onClick={approveAll} className="primary-button">{assessment.is_preliminary ? "Approve preliminary" : "Approve final assessment"}</button> : null}</div>
    </div>
    {error ? <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{error}</div> : null}

    {!assessment ? <section className="panel mt-6 p-6"><h2 className="section-title">No assessment generated yet</h2><p className="section-subtitle">A readiness gate prevents accidental generation when critical evidence is missing.</p><label className="mt-5 block"><span className="label">Preliminary override reason</span><textarea className="field resize-none" rows={3} value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} /></label><button disabled={busy} onClick={() => generate(true)} className="secondary-button mt-3">Generate preliminary draft</button></section> : <>
      <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">Version</p><p className="metric-value">v{assessment.version}</p></div>
        <div className="panel p-5"><p className="metric-label">Readiness</p><p className="metric-value">{assessment.readiness_score}%</p><p className="mt-1 text-xs text-slate-500">{assessment.readiness_state.replaceAll("_", " ")}</p></div>
        <div className="panel p-5"><p className="metric-label">Assessment status</p><p className="metric-value text-xl capitalize">{assessment.status.replaceAll("_", " ")}</p></div>
        <div className="panel p-5"><p className="metric-label">Classification</p><p className={`metric-value text-xl ${assessment.is_preliminary ? "text-amber-700" : "text-emerald-700"}`}>{assessment.is_preliminary ? "Preliminary" : "Ready"}</p></div>
      </section>
      {assessment.blocking_items.length ? <section className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-5"><h2 className="text-sm font-semibold text-amber-950">Outstanding blocking evidence</h2><ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-900">{assessment.blocking_items.map((x) => <li key={x}>{x}</li>)}</ul><p className="mt-3 text-xs text-amber-700">This assessment is preliminary and remains subject to the outstanding evidence above.</p></section> : null}
      {assessment.status === "approved" ? <section className={`mt-5 rounded-xl border p-5 ${assessment.is_preliminary ? "border-amber-300 bg-amber-50" : "border-emerald-300 bg-emerald-50"}`}><h2 className={`text-sm font-semibold ${assessment.is_preliminary ? "text-amber-950" : "text-emerald-950"}`}>{assessment.is_preliminary ? "Approved preliminary assessment — not final" : "Final initial assessment approved"}</h2><p className={`mt-2 text-xs leading-5 ${assessment.is_preliminary ? "text-amber-800" : "text-emerald-800"}`}>{assessment.is_preliminary ? "This version was approved for interim claims handling while blocking evidence remained outstanding. Once the evidence position improves, generate a new version; only a non-preliminary version should be treated as the final Initial Assessment." : "This non-preliminary version passed the readiness gate and all sections were human-reviewed before approval."}</p></section> : null}
      <div className="mt-6 space-y-5">{assessment.sections.map((section) => {
        const text = section.approved_text ?? section.draft_text;
        return <section key={section.id} className="panel p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><p className="eyebrow">{String(section.sort_order / 10).padStart(2, "0")}</p><h2 className="section-title mt-1">{section.title}</h2><p className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{section.status}</p></div><div className="flex gap-2"><button disabled={busy} onClick={() => review(section.id, "approve")} className="secondary-button">Approve</button><button disabled={busy} onClick={() => { setEditing({ ...editing, [section.id]: editing[section.id] ?? text }); }} className="secondary-button">Edit</button></div></div>
          {editing[section.id] !== undefined ? <div className="mt-4"><textarea rows={7} className="field resize-y" value={editing[section.id]} onChange={(e) => setEditing({ ...editing, [section.id]: e.target.value })} /><div className="mt-2 flex gap-2"><button disabled={busy} onClick={() => review(section.id, "edit")} className="primary-button">Save edited section</button><button onClick={() => { const next={...editing}; delete next[section.id]; setEditing(next); }} className="secondary-button">Cancel</button></div></div> : <div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-700">{text}</div>}
          <details className="mt-5 border-t border-slate-200 pt-4"><summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">Sources ({section.source_manifest.length})</summary><div className="mt-3 space-y-2">{section.source_manifest.length ? section.source_manifest.map((s, i) => <div key={`${s.id}-${i}`} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600"><span className="font-semibold">{s.kind}</span> · {s.label}</div>) : <p className="text-xs text-slate-400">No structured source records linked.</p>}</div></details>
        </section>;
      })}</div>
      <div className="mt-6 flex justify-end"><button disabled={busy || assessment.status === "approved"} onClick={approveAll} className="primary-button">{assessment.is_preliminary ? "Approve preliminary" : "Approve final assessment"}</button></div>
    </>}
  </div>;
}
