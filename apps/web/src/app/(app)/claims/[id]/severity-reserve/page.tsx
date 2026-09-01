"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, getClaim } from "@/lib/api";
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

function amount(value: string | number | null, currency: string | null) {
  if (value === null || value === undefined || !currency) return "Not calculated";
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
      setError(e instanceof ApiError ? e.detail : "Severity & reserve support workspace could not be loaded.");
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
      setMessage(`Support snapshot v${next.snapshot_version} is ready.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Severity & reserve support could not be refreshed.");
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
    if (note.trim().length < 5) { setError("Add a short human-review note before recording a decision."); return; }
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
      setMessage("Human disposition recorded. Authoritative reserve state was not changed.");
      setNote("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Human disposition could not be recorded.");
    } finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading severity & reserve support…</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || "Claim unavailable."}</div>;

  const severity = snapshot?.evaluations.find((row) => row.kind === "severity") ?? null;
  const reserve = snapshot?.evaluations.find((row) => row.kind === "reserve") ?? null;

  return <div className="space-y-6">
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to {claim.vessel.name}</Link>
    <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
      <div>
        <p className="eyebrow">{claim.claim_reference} · Phase 12D</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Severity & Reserve Support</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">Explainable handling-priority and reserve-range review support from current source-linked evidence. No FX rate, reserve, policy amount or future cost is invented.</p>
      </div>
      <button onClick={refresh} disabled={busy} className="primary-button disabled:opacity-40">{busy ? "Working…" : snapshot ? "Refresh support" : "Build support"}</button>
    </div>

    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
      <strong>Human reserve authority required.</strong> {disclaimer || "This workspace never creates or changes an authoritative reserve."}
    </div>
    {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
    {message ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</div> : null}

    {!snapshot ? <section className="panel p-8 text-center"><h2 className="section-title">No support snapshot yet</h2><p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">Build support after financial evidence and claim facts have been human-reviewed. Missing or mixed-currency evidence remains explicit and does not create a guessed range.</p></section> : <>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">Snapshot</p><p className="metric-value">v{snapshot.snapshot_version}</p><p className="mt-1 text-xs text-slate-400">Engine {snapshot.engine_version}</p></div>
        <div className={`rounded-xl border p-5 ${severityTone(severity?.severity_label ?? null)}`}><p className="metric-label">Handling severity</p><p className="mt-2 text-2xl font-semibold capitalize">{severity?.severity_label ?? "Not available"}</p><p className="mt-1 text-xs">Score {severity?.severity_score ?? 0} · workflow priority only</p></div>
        <div className="panel p-5"><p className="metric-label">Reserve support</p><p className="mt-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusTone(reserve?.status ?? "not_applicable")}`}>{(reserve?.status ?? "not applicable").replaceAll("_", " ")}</span></p></div>
        <div className="panel p-5"><p className="metric-label">Candidate range</p><p className="mt-2 text-sm font-semibold text-slate-950">{reserve?.status === "triggered" ? `${amount(reserve.lower_amount, reserve.currency)} – ${amount(reserve.upper_amount, reserve.currency)}` : "Not calculated"}</p><p className="mt-1 text-xs text-slate-400">Never writes ReserveHistory</p></div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)]">
        <section className="panel p-5">
          <h2 className="section-title">Evaluations</h2><p className="section-subtitle">Select an immutable evaluation to inspect factors, evidence gaps and human disposition.</p>
          <div className="mt-4 space-y-3">{snapshot.evaluations.map((row) => <button key={row.id} onClick={() => choose(row)} className={`w-full rounded-xl border p-4 text-left transition ${selected?.id === row.id ? "border-cyan-400 bg-cyan-50/60" : "border-slate-200 hover:bg-slate-50"}`}>
            <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">{row.kind}</p><h3 className="mt-1 text-sm font-semibold text-slate-950">{row.title}</h3></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ring-1 ${statusTone(row.status)}`}>{row.status.replaceAll("_", " ")}</span></div>
            {row.kind === "severity" ? <p className="mt-3 text-xs font-semibold capitalize text-slate-600">{row.severity_label} · score {row.severity_score}</p> : <p className="mt-3 text-xs font-semibold text-slate-600">{row.status === "triggered" ? `${amount(row.lower_amount, row.currency)} – ${amount(row.upper_amount, row.currency)}` : "No evidence-grounded range"}</p>}
          </button>)}</div>
        </section>

        {selected ? <section className="panel p-6">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">{selected.kind} · {selected.status.replaceAll("_", " ")}</p><h2 className="mt-1 text-xl font-semibold text-slate-950">{selected.title}</h2></div>{selected.kind === "severity" ? <span className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize ${severityTone(selected.severity_label)}`}>{selected.severity_label} · {selected.severity_score}</span> : null}</div>

          {selected.kind === "reserve" ? <dl className="mt-5 grid gap-4 sm:grid-cols-3"><div><dt className="detail-label">Currency</dt><dd className="detail-value">{selected.currency ?? "—"}</dd></div><div><dt className="detail-label">Observed floor</dt><dd className="detail-value">{amount(selected.lower_amount, selected.currency)}</dd></div><div><dt className="detail-label">Upper evidence point</dt><dd className="detail-value">{amount(selected.upper_amount, selected.currency)}</dd></div></dl> : null}

          <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="detail-label">Candidate implication</p><p className="mt-2 text-sm leading-6 text-slate-700">{selected.candidate_implication}</p><p className="detail-label mt-4">Recommended human action</p><p className="mt-2 text-sm leading-6 text-slate-700">{selected.recommended_action}</p></div>
          <div className="mt-4"><p className="detail-label">Rationale</p><p className="mt-2 text-sm leading-6 text-slate-600">{selected.rationale}</p></div>

          <div className="mt-5"><p className="detail-label">Explainable factors</p><div className="mt-2 space-y-2">{selected.factors.map((factor, index) => <div key={index} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{JSON.stringify(factor)}</div>)}</div></div>
          {selected.missing_prerequisites.length ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-amber-800">Evidence / currency gaps</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{selected.missing_prerequisites.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}

          <div className="mt-5"><p className="detail-label">Source lineage</p><div className="mt-2 space-y-2">{selected.source_refs.length ? selected.source_refs.map((source, index) => <div key={index} className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600"><p className="font-semibold text-slate-700">{sourceLabel(source)}</p><pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[10px] text-slate-400">{JSON.stringify(source)}</pre></div>) : <p className="text-sm text-slate-400">No material monetary source is available for this evidence-gap evaluation.</p>}</div></div>

          {selected.latest_decision ? <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-violet-700">Latest human decision · #{selected.latest_decision.decision_number}</p><p className="mt-2 text-sm font-semibold capitalize text-slate-900">{selected.latest_decision.action.replaceAll("_", " ")}</p><p className="mt-1 text-sm text-slate-600">{selected.latest_decision.note}</p></div> : null}

          <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="text-sm font-semibold text-slate-950">Record human disposition</h3><p className="mt-1 text-xs leading-5 text-slate-500">The immutable support output is not edited. This decision is append-only and does not update the authoritative reserve.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2"><label><span className="label">Decision</span><select className="field" value={action} onChange={(e) => setAction(e.target.value as SeverityReserveDecisionAction)}><option value="accept">Accept as review support</option><option value="edit">Edit human interpretation</option><option value="dismiss">Dismiss</option><option value="not_applicable">Not applicable</option></select></label>{action === "edit" && selected.kind === "severity" ? <label><span className="label">Human severity</span><select className="field" value={editedSeverity} onChange={(e) => setEditedSeverity(e.target.value as typeof editedSeverity)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label> : null}</div>
            {action === "edit" && selected.kind === "reserve" ? <div className="mt-3 grid gap-3 sm:grid-cols-2"><label><span className="label">Human lower amount</span><input className="field" type="number" min="0" value={editedLower} onChange={(e) => setEditedLower(e.target.value)} /></label><label><span className="label">Human upper amount</span><input className="field" type="number" min="0" value={editedUpper} onChange={(e) => setEditedUpper(e.target.value)} /></label></div> : null}
            <label className="mt-3 block"><span className="label">Human review note</span><textarea className="field min-h-24" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Record why this support output is accepted, edited, dismissed or not applicable." /></label>
            <button onClick={decide} disabled={busy} className="primary-button mt-4 disabled:opacity-40">Record human disposition</button>
            <p className="mt-3 text-xs font-semibold text-rose-700">There is deliberately no “Set reserve automatically” action in this workspace.</p>
          </div>
        </section> : null}
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 text-[11px] text-slate-500"><p>Engine {snapshot.engine_version} · generated {new Date(snapshot.generated_at).toLocaleString()}</p><p className="mt-1 break-all font-mono">Source-state SHA-256: {snapshot.source_state_hash}</p><p className="mt-1 break-all font-mono">Snapshot SHA-256: {snapshot.snapshot_hash}</p></section>
    </>}
  </div>;
}
