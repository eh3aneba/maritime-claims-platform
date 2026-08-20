"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  ApiError, attestAILimitedProductionDocument, completeAILimitedProduction,
  createAILimitedProduction, decideAILimitedProduction, getAILimitedProduction,
  getAIPilotOutcomes, monitorAILimitedProduction, reportAILimitedProductionIncident,
  resolveAILimitedProductionIncident, resumeAILimitedProduction,
  reviewAILimitedProduction, reviewAILimitedProductionRun, revokeAILimitedProduction,
} from "@/lib/api";
import type {
  AILimitedProductionAuthorization, AILimitedProductionDashboard,
  AIPilotOutcomeDashboard,
} from "@/lib/types";

const controlClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

function badge(status: string) {
  if (["authorized", "completed", "eligible", "human_reviewed", "pass", "resolved"].includes(status)) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (["held", "rejected", "revoked", "paused", "rollback_required", "open"].includes(status)) return "bg-rose-50 text-rose-700 ring-rose-200";
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function Badge({ value }: { value: string }) {
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${badge(value)}`}>{value.replaceAll("_", " ")}</span>;
}

export default function AILimitedProductionPage() {
  const [dashboard, setDashboard] = useState<AILimitedProductionDashboard | null>(null);
  const [outcomes, setOutcomes] = useState<AIPilotOutcomeDashboard | null>(null);
  const [claimId, setClaimId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [authorizationData, outcomeData] = await Promise.all([
        getAILimitedProduction(), getAIPilotOutcomes(),
      ]);
      setDashboard(authorizationData); setOutcomes(outcomeData); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load the limited-production controls.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const current = dashboard?.authorizations[0] ?? null;
  const recommendation = outcomes?.assessments.find(
    (item) => item.status === "recommended"
      && item.outcome === "recommend_limited_production_evaluation") ?? null;
  const canCreate = recommendation && (!current
    || current.outcome_assessment_id !== recommendation.id
    || ["held", "rejected", "revoked", "completed"].includes(current.status));

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "The limited-production action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!recommendation) { setError("A positive Sprint 11D recommendation is required."); return; }
    await run("create", () => createAILimitedProduction(recommendation.id),
      "A separate expiring authorization attempt was created; no Production access was granted.");
  }

  async function attest(event: FormEvent) {
    event.preventDefault();
    if (!current) return;
    await run("attest", () => attestAILimitedProductionDocument(current.id, {
      claim_id: claimId, document_id: documentId,
      note: "Manager verified legal basis, data minimization, current version, non-restricted classification and rollout eligibility.",
    }), "Document entered the deterministic rollout cohort without copying content to the ledger.");
    setClaimId(""); setDocumentId("");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11E · separately authorized evaluation</p>
      <h1 className="mt-3 text-3xl font-semibold">Limited-production AI control plane</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">A positive pilot outcome is only an anchor. Production evaluation additionally requires four independent approvals, Admin authorization, isolated provider controls, deterministic rollout, per-document eligibility, different-human review, live monitoring, expiry and immediate rollback.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Authorization", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Rollout", current ? `${current.rollout_percentage}%` : "0%"],
        ["Human review", current ? `${current.summary.human_reviewed_run_count}/${current.summary.provider_run_count}` : "0/0"],
        ["Production-wide", "Blocked"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize text-slate-900">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Create a seven-day, 10% maximum evaluation attempt</h2>
      <p className="mt-2 text-sm text-slate-600">Anchor: Sprint 11D assessment {recommendation?.id}. Defaults: 5 claims, 15 documents, 5 users and 50 provider runs; rollback SLO is 15 minutes.</p>
      <button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create separate authorization</button>
    </section>}

    {current && <AuthorizationControl item={current} busy={busy} run={run} />}

    {current?.summary.authorization_active && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Attest one non-restricted rollout document</h2>
      <p className="mt-2 text-sm text-slate-600">The API verifies tenant, current version, legal/data-minimization references, CE/Engine allowlist and deterministic bucket below {current.rollout_percentage}.</p>
      <form onSubmit={attest} className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <input required value={claimId} onChange={(event) => setClaimId(event.target.value)} className={controlClass} placeholder="Claim UUID" />
        <input required value={documentId} onChange={(event) => setDocumentId(event.target.value)} className={controlClass} placeholder="Document UUID" />
        <button disabled={busy !== null} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Attest rollout document</button>
      </form>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Document rollout cohort</h2>
      <div className="mt-4 space-y-2">{current?.document_eligibility.length ? current.document_eligibility.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.document_type.replaceAll("_", " ")} · bucket {item.rollout_bucket}</p><p className="mt-1 text-xs text-slate-500">Document {item.document_id} · SHA-256 {item.snapshot_hash.slice(0, 12)}…</p></div><Badge value={item.status} /></div>) : <p className="text-sm text-slate-500">No document has limited-production eligibility.</p>}</div>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Provider runs and mandatory different-human review</h2>
      <div className="mt-4 space-y-2">{current?.runs.length ? current.runs.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.task_type.replaceAll("_", " ")} · job {item.processing_job_id}</p><p className="mt-1 text-xs text-slate-500">Requested by {item.requested_by_id ?? "unknown"}{item.outcome_hash ? ` · ${item.outcome_hash.slice(0, 12)}…` : ""}</p></div><div className="flex items-center gap-2"><Badge value={item.status} /><button disabled={busy !== null || item.status !== "queued"} onClick={() => void run(`run-${item.id}`, () => reviewAILimitedProductionRun(item.id, "approve"), "Different-human review outcome recorded.")} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Human approve</button></div></div>) : <p className="text-sm text-slate-500">No production-evaluation run has been reserved.</p>}</div>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Live monitors</h2>
      <div className="mt-4 space-y-2">{current?.monitors.length ? current.monitors.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.monitor_key}</p><p className="mt-1 text-xs text-slate-500">{new Date(item.monitored_at).toLocaleString()} · SHA-256 {item.monitor_hash.slice(0, 12)}…{item.failure_reasons.length ? ` · ${item.failure_reasons.join(", ")}` : ""}</p></div><Badge value={item.status} /></div>) : <p className="text-sm text-slate-500">No live monitor snapshot recorded.</p>}</div>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Incident and rollback ledger</h2>
      <div className="mt-4 space-y-2">{current?.incidents.length ? current.incidents.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium capitalize">{item.severity} · {item.category.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-500">{item.evidence_reference} · {item.note}</p></div><div className="flex items-center gap-2"><Badge value={item.status} /><button disabled={busy !== null || item.status !== "open"} onClick={() => void run(`resolve-${item.id}`, () => resolveAILimitedProductionIncident(current.id, item.id), "Incident resolved; a new passing monitor is still required before resume.")} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold disabled:opacity-40">Admin resolve</button></div></div>) : <p className="text-sm text-slate-500">No incident recorded.</p>}</div>
    </section>

    <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900"><strong>Hard boundary:</strong> this page can authorize only an expiring limited-production evaluation. Production-wide use, Restricted documents, rollout expansion, autonomous claim decisions and automatic authoritative fact updates remain prohibited. Full English/Persian UI localization remains deferred.</section>
  </div>;
}

function AuthorizationControl({ item, busy, run }: { item: AILimitedProductionAuthorization; busy: string | null; run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void> }) {
  const reviewed = new Set(item.approvals.map((approval) => approval.approval_role));
  const roles = ["security", "privacy", "product", "operations"] as const;
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {item.attempt_number} · {item.evaluation_mode.replaceAll("_", " ")}</p><h2 className="mt-1 text-xl font-semibold">{item.authorization_key}</h2><p className="mt-1 text-xs text-slate-500">{item.model} · {item.rollout_percentage}% · {new Date(item.expires_at).toLocaleString()} expiry</p></div><Badge value={item.status} /></div>
    <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
      {roles.map((role) => <button key={role} disabled={busy !== null || reviewed.has(role) || !["pending_approvals", "decision_ready"].includes(item.status)} onClick={() => void run(`approve-${role}`, () => reviewAILimitedProduction(item.id, role, "approve"), `${role} approval recorded.`)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role} approve</button>)}
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("authorize", () => decideAILimitedProduction(item.id, "authorize_limited_evaluation"), "Admin authorized only the exact limited evaluation.")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Admin authorize</button>
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("hold", () => decideAILimitedProduction(item.id, "hold"), "Authorization held; Production AI remains blocked.")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Admin hold</button>
      <button disabled={busy !== null || !["authorized", "paused"].includes(item.status) || item.summary.provider_run_count === 0} onClick={() => void run("monitor", () => monitorAILimitedProduction(item.id), "Live monitor snapshot recorded; failures pause execution.")} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Run live monitor</button>
      <button disabled={busy !== null || item.status !== "authorized"} onClick={() => void run("incident", () => reportAILimitedProductionIncident(item.id), "Incident recorded; execution paused and rollback triggered.")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Incident + rollback</button>
      <button disabled={busy !== null || item.status !== "paused" || item.summary.open_incident_count > 0 || !item.summary.monitor_fresh_and_passing} onClick={() => void run("resume", () => resumeAILimitedProduction(item.id), "Admin resumed after remediation and a passing monitor.")} className="rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-40">Admin resume</button>
      <button disabled={busy !== null || !["authorized", "paused"].includes(item.status)} onClick={() => void run("revoke", () => revokeAILimitedProduction(item.id), "Kill switch activated immediately.")} className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Revoke</button>
      <button disabled={busy !== null || !["authorized", "paused"].includes(item.status) || item.summary.provider_run_count === 0 || item.summary.pending_human_review_count > 0 || item.summary.open_incident_count > 0 || !item.summary.monitor_fresh_and_passing} onClick={() => void run("complete", () => completeAILimitedProduction(item.id), "Evaluation completed; Production-wide use remains unauthorized.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Admin complete</button>
    </div>
    <p className="mt-3 text-xs text-slate-500">Requester and four reviewers must be five different people. Switch accounts for each approval; only Admin can authorize, resume or complete.</p>
    {item.decision_hash && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {item.decision_hash}</p>}
  </section>;
}
