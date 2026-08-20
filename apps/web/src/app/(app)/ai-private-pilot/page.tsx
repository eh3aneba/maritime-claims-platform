"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  ApiError, attestAIPrivatePilotDocument, completeAIPrivatePilot,
  createAIPrivatePilot, decideAIPrivatePilot, getAIEvaluation, getAIPrivatePilot,
  reportAIPrivatePilotIncident, resolveAIPrivatePilotIncident,
  reviewAIPrivatePilot, reviewAIPrivatePilotRun, revokeAIPrivatePilot,
  revokeAIPrivatePilotDocument,
} from "@/lib/api";
import type { AIEvaluationDashboard, AIPrivatePilot, AIPrivatePilotDashboard } from "@/lib/types";

const controlClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

function badge(status: string) {
  if (["authorized", "completed", "eligible", "human_reviewed", "resolved"].includes(status)) {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }
  if (["held", "rejected", "revoked", "paused", "open"].includes(status)) {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function Badge({ value }: { value: string }) {
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${badge(value)}`}>{value.replaceAll("_", " ")}</span>;
}

export default function AIPrivatePilotPage() {
  const [dashboard, setDashboard] = useState<AIPrivatePilotDashboard | null>(null);
  const [evaluation, setEvaluation] = useState<AIEvaluationDashboard | null>(null);
  const [claimId, setClaimId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [pilotData, evaluationData] = await Promise.all([getAIPrivatePilot(), getAIEvaluation()]);
      setDashboard(pilotData); setEvaluation(evaluationData); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load the private-pilot controls.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const current = dashboard?.pilots[0] ?? null;
  const activePromotion = evaluation?.suites.find((item) => item.summary.promotion_active) ?? null;
  const canCreate = !current || ["held", "rejected", "revoked", "completed"].includes(current.status)
    || (current.status === "authorized" && new Date(current.expires_at).getTime() <= Date.now());

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "The private-pilot action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!activePromotion) { setError("An active Sprint 11B staging promotion is required."); return; }
    await run("create", () => createAIPrivatePilot(
      activePromotion.id, activePromotion.promotion_expires_at),
      "A bounded real-document pilot authorization attempt was created.");
  }

  async function attest(event: FormEvent) {
    event.preventDefault();
    if (!current) return;
    await run("attest", () => attestAIPrivatePilotDocument(current.id, {
      claim_id: claimId, document_id: documentId,
      authorization_basis: "organization_and_data_owner",
      authorization_reference: `artifact://ai-pilot/document-${documentId}-authorization`,
      data_minimization_reference: `artifact://ai-pilot/document-${documentId}-minimization`,
      note: "Manager confirmed this current document is real, non-restricted, allowlisted and minimized.",
    }), "Document added to the bounded cohort; its content was not copied into this ledger.");
    setClaimId(""); setDocumentId("");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11C · bounded private pilot</p>
      <h1 className="mt-3 text-3xl font-semibold">Real non-restricted document AI pilot</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Real claim documents remain blocked unless the organization owner and data owner independently approve an expiring cohort, an Admin authorizes it, and each document is individually attested. Every AI result remains a candidate until a different human reviews it.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Pilot status", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Claims", current ? `${current.summary.active_claim_count}/${current.max_claims}` : "0/—"],
        ["Documents", current ? `${current.summary.active_document_count}/${current.max_documents}` : "0/—"],
        ["Human review", current ? `${current.summary.human_reviewed_run_count}/${current.summary.provider_run_count}` : "0/0"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize text-slate-900">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Create a seven-day private-pilot attempt</h2>
      <p className="mt-2 text-sm text-slate-600">Anchor: {activePromotion ? `${activePromotion.activation_model} · evaluation ${activePromotion.id}` : "no active Sprint 11B promotion"}. Default caps are 3 claims, 10 documents, 5 users and 30 provider runs.</p>
      <button disabled={!activePromotion || busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create authorization attempt</button>
    </section>}

    {current && <PilotControl item={current} busy={busy} run={run} />}

    {current?.summary.authorization_active && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Attest one real non-restricted document</h2>
      <p className="mt-2 text-sm text-slate-600">Use the Claim and Document UUIDs shown in the claim workspace. The API verifies tenant, current version, confidentiality, allowlist and cohort caps.</p>
      <form onSubmit={attest} className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <input required value={claimId} onChange={(event) => setClaimId(event.target.value)} className={controlClass} placeholder="Claim UUID" />
        <input required value={documentId} onChange={(event) => setDocumentId(event.target.value)} className={controlClass} placeholder="Document UUID" />
        <button disabled={busy !== null} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Attest document</button>
      </form>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Document cohort</h2>
      <div className="mt-4 space-y-2">{current?.document_eligibility.length ? current.document_eligibility.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.document_type.replaceAll("_", " ")} · {item.document_id}</p><p className="mt-1 text-xs text-slate-500">Claim {item.claim_id} · SHA-256 {item.snapshot_hash.slice(0, 12)}… · {item.confidentiality_level}</p></div><div className="flex items-center gap-2"><Badge value={item.status} /><button disabled={busy !== null || item.status !== "eligible"} onClick={() => void run(`doc-${item.id}`, () => revokeAIPrivatePilotDocument(current.id, item.id), "Document eligibility revoked immediately.")} className="rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-40">Revoke</button></div></div>) : <p className="text-sm text-slate-500">No real document has been attested.</p>}</div>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Provider runs and mandatory human review</h2>
      <p className="mt-2 text-sm text-slate-600">Queued runs appear after an authorized document is sent through its claim Intelligence action. Switch to a different user before recording the review.</p>
      <div className="mt-4 space-y-2">{current?.runs.length ? current.runs.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.task_type.replaceAll("_", " ")} · job {item.processing_job_id}</p><p className="mt-1 text-xs text-slate-500">Requested by {item.requested_by_id ?? "unknown"}{item.outcome_hash ? ` · outcome ${item.outcome_hash.slice(0, 12)}…` : ""}</p></div><div className="flex items-center gap-2"><Badge value={item.status} /><button disabled={busy !== null || item.status !== "queued"} onClick={() => void run(`run-${item.id}`, () => reviewAIPrivatePilotRun(item.id, "approve"), "Human-review outcome recorded; replace the UI sample metrics with observed values when operating the pilot.")} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Human approve</button></div></div>) : <p className="text-sm text-slate-500">No provider run has been reserved.</p>}</div>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Incident and rollback ledger</h2>
      <div className="mt-4 space-y-2">{current?.incidents.length ? current.incidents.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium capitalize">{item.severity} · {item.category.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-500">{item.evidence_reference} · {item.note}</p></div><div className="flex items-center gap-2"><Badge value={item.status} /><button disabled={busy !== null || item.status !== "open"} onClick={() => void run(`resolve-${item.id}`, () => resolveAIPrivatePilotIncident(current.id, item.id), "Admin resolved the incident and resumed only after verifying remediation.")} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold disabled:opacity-40">Admin resolve + resume</button></div></div>) : <p className="text-sm text-slate-500">No incident recorded.</p>}</div>
    </section>

    <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900"><strong>Hard boundary:</strong> this authorization never covers Restricted data, broad production use, autonomous liability/coverage/reserve/settlement/payment decisions, or automatic updates to authoritative claim facts. Full English/Persian UI localization remains deferred.</section>
  </div>;
}

function PilotControl({ item, busy, run }: { item: AIPrivatePilot; busy: string | null; run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void> }) {
  const reviewed = new Set(item.approvals.map((approval) => approval.approval_role));
  const openIncident = item.incidents.some((incident) => incident.status === "open");
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {item.attempt_number} · {item.data_mode.replaceAll("_", " ")}</p><h2 className="mt-1 text-xl font-semibold">{item.pilot_key}</h2><p className="mt-1 text-xs text-slate-500">{new Date(item.starts_at).toLocaleString()} → {new Date(item.expires_at).toLocaleString()} · {item.max_provider_runs} max runs</p></div><Badge value={item.status} /></div>
    <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
      <button disabled={busy !== null || reviewed.has("organization_owner") || !["pending_approvals", "decision_ready"].includes(item.status)} onClick={() => void run("organization-owner", () => reviewAIPrivatePilot(item.id, "organization_owner", "approve"), "Organization-owner approval recorded.")} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-40">Organization owner approve</button>
      <button disabled={busy !== null || reviewed.has("data_owner") || !["pending_approvals", "decision_ready"].includes(item.status)} onClick={() => void run("data-owner", () => reviewAIPrivatePilot(item.id, "data_owner", "approve"), "Data-owner approval recorded.")} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-40">Data owner approve</button>
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("authorize", () => decideAIPrivatePilot(item.id, "authorize_pilot"), "Admin authorized the exact bounded cohort.")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Admin authorize pilot</button>
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("hold", () => decideAIPrivatePilot(item.id, "hold"), "Pilot held; real-document AI remains blocked.")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Admin hold</button>
      <button disabled={busy !== null || item.status !== "authorized"} onClick={() => void run("incident", () => reportAIPrivatePilotIncident(item.id), "High-severity incident recorded; pilot paused immediately.")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Report incident + pause</button>
      <button disabled={busy !== null || !["authorized", "paused"].includes(item.status)} onClick={() => void run("revoke", () => revokeAIPrivatePilot(item.id), "Private-pilot kill switch activated.")} className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Revoke pilot</button>
      <button disabled={busy !== null || !["authorized", "paused"].includes(item.status) || item.summary.pending_human_review_count > 0 || item.summary.provider_run_count === 0 || openIncident} onClick={() => void run("complete", () => completeAIPrivatePilot(item.id), "Bounded pilot completed; production authorization remains a separate future decision.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Admin complete pilot</button>
    </div>
    <p className="mt-3 text-xs text-slate-500">Requester, organization owner and data owner must be three different people. Only Admin can authorize or complete. Use separate user accounts for the two approvals.</p>
    {item.decision_hash && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {item.decision_hash}</p>}
  </section>;
}
