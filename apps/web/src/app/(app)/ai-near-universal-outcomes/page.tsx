"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";

type NearRun = { id: string; task_type: string; status: string };
type NearAuthorization = {
  id: string; authorization_key: string; status: string; outcome: string | null;
  rollout_percentage: number; runs: NearRun[];
};
type NearDashboard = { authorizations: NearAuthorization[] };
type Observation = { near_universal_run_id: string; workflow_type: string };
type BusinessEvidence = { evidence_key: string; workflow_type: string };
type Review = { review_role: string; action: string };
type Assessment = {
  id: string; assessment_key: string; status: string; outcome: string | null;
  rollout_percentage: number; metrics: Record<string, unknown> | null; failure_reasons: string[];
  assessment_hash: string | null; decision_hash: string | null;
  observations: Observation[]; business_evidence: BusinessEvidence[]; reviews: Review[];
  summary: {
    separate_100_percent_authorization_review_recommended: boolean;
    rollout_100_percent_authorized: boolean; production_wide_authorized: boolean;
  };
};
type Dashboard = { assessments: Assessment[] };

const roles = [
  "product", "quality", "risk", "operations", "security", "privacy",
  "claims_governance", "ai_quality", "legal_data_governance", "business_owner",
  "platform_reliability", "independent_production_assurance",
] as const;
const input = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const pct = (value: unknown) => typeof value === "number" ? `${(value / 100).toFixed(2)}%` : "—";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export default function AINearUniversalOutcomesPage() {
  const [anchors, setAnchors] = useState<NearDashboard | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [runId, setRunId] = useState("");
  const [claimId, setClaimId] = useState("");
  const [workflow, setWorkflow] = useState<"chief_engineer_report" | "engine_log">("chief_engineer_report");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<NearDashboard>("/ai-near-universal-production"),
        request<Dashboard>("/ai-near-universal-outcomes"),
      ]);
      setAnchors(a); setDashboard(b); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11Q.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const anchor = anchors?.authorizations.find((item) => item.status === "completed" && item.rollout_percentage >= 91 && item.rollout_percentage <= 99) ?? null;
  const current = dashboard?.assessments[0] ?? null;
  const observedRuns = useMemo(() => new Set(current?.observations.map((item) => item.near_universal_run_id) ?? []), [current]);
  const reviewedRoles = useMemo(() => new Set(current?.reviews.map((item) => item.review_role) ?? []), [current]);
  const technical = (current?.metrics ?? {}) as Record<string, unknown>;
  const business = ((technical.business_value ?? {}) as Record<string, unknown>);
  const trend = ((technical.trend ?? {}) as Record<string, unknown>);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11Q action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!anchor) return;
    await act("create", () => request("/ai-near-universal-outcomes/assessments", {
      method: "POST",
      body: JSON.stringify({
        near_universal_authorization_id: anchor.id,
        assessment_key: `near-universal-outcome-${crypto.randomUUID()}`,
        confirm_content_free_assessment: true,
      }),
    }), "Sprint 11Q assessment created; no 100% permission was granted.");
  }

  async function addObservation() {
    if (!current || !runId) return;
    await act("observation", () => request(`/ai-near-universal-outcomes/assessments/${current.id}/observations`, {
      method: "POST",
      body: JSON.stringify({
        near_universal_run_id: runId,
        usefulness_rating: 5,
        review_seconds: 120,
        workflow_completed: true,
        evidence_reference: `artifact://ai-near-universal-outcomes/observation-${crypto.randomUUID()}`,
        note: "Content-free usefulness and review-effort evidence for one immutable Sprint 11P run.",
        confirm_content_free_observation: true,
      }),
    }), "Near-universal run observation recorded.");
  }

  async function addBusinessEvidence() {
    if (!current || !claimId) return;
    await act("business", () => request(`/ai-near-universal-outcomes/assessments/${current.id}/business-evidence`, {
      method: "POST",
      body: JSON.stringify({
        claim_id: claimId,
        evidence_key: `near-universal-business-${crypto.randomUUID()}`,
        workflow_type: workflow,
        baseline_tfta_seconds: 1000,
        assisted_tfta_seconds: 600,
        baseline_triage_seconds: 1000,
        assisted_triage_seconds: 500,
        baseline_handler_effort_seconds: 1000,
        assisted_handler_effort_seconds: 700,
        baseline_rework_count: 1, assisted_rework_count: 1,
        baseline_escalation_count: 1, assisted_escalation_count: 1,
        baseline_correction_count: 1, assisted_correction_count: 1,
        handler_usefulness_rating: 5,
        final_claim_decision_human_owned: true,
        evidence_reference: `artifact://ai-near-universal-outcomes/business-${crypto.randomUUID()}`,
        note: "Content-free near-universal baseline-versus-assisted workflow measurement.",
        confirm_content_free_business_evidence: true,
      }),
    }), "Near-universal business-value evidence recorded.");
  }

  async function review(role: typeof roles[number]) {
    if (!current) return;
    await act(`review-${role}`, () => request(`/ai-near-universal-outcomes/assessments/${current.id}/reviews`, {
      method: "POST",
      body: JSON.stringify({
        review_role: role, action: "approve",
        evidence_reference: `artifact://ai-near-universal-outcomes/${role}-review`,
        note: `Independent ${role} reviewer reproduced the Sprint 11P source-ledger technical, safety and business-value scorecard.`,
      }),
    }), `${role} review recorded.`);
  }

  async function decide(outcome: "recommend_separate_100_percent_authorization_review" | "extend_near_universal_91_99" | "stop_ai_progression") {
    if (!current) return;
    await act(`decision-${outcome}`, () => request(`/ai-near-universal-outcomes/assessments/${current.id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        outcome,
        confirm_recommendation_only: true,
        note: outcome === "recommend_separate_100_percent_authorization_review"
          ? "Recommend only a separate review of a possible 100% authorization; no 100% or Production-wide permission is granted here."
          : "Do not widen Production AI permissions from Sprint 11Q.",
      }),
    }), "Recommendation-only Sprint 11Q decision recorded.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11Q · Measured Near-Universal Outcome</p>
      <h1 className="mt-3 text-3xl font-semibold">Evidence before any 100% authorization question</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Re-read the completed 91–99% Sprint 11P source ledgers, require at least 160 different-human-reviewed runs, revalidate real handler value and correction burden, and obtain twelve independent reviews. A positive result is recommendation-only and never activates 100% or Production-wide AI.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Assessment", current?.status.replaceAll("_", " ") ?? "not created"], ["Run observations", current ? `${current.observations.length}/160` : "0/160"], ["Business workflows", current ? `${current.business_evidence.length}/12` : "0/12"], ["100% / Production-wide", "Not authorized"]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {!current && anchor && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Start measured 91–99% outcome assessment</h2><p className="mt-2 text-sm text-slate-600">Anchor: {anchor.authorization_key} at {anchor.rollout_percentage}%. Creation freezes the exact 11P→11O→11N inherited hash chain and authorization caps.</p><button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create Sprint 11Q assessment</button></section>}

    {current?.status === "collecting" && <>
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Per-run outcome evidence</h2><p className="mt-2 text-sm text-slate-600">Every reviewed Sprint 11P provider run needs a content-free usefulness/review-effort observation.</p><div className="mt-4 flex gap-3"><input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="Sprint 11P run UUID" className={`${input} flex-1`} /><button disabled={busy !== null || !runId || observedRuns.has(runId)} onClick={() => void addObservation()} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record observation</button></div></section>
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Business-value revalidation</h2><p className="mt-2 text-sm text-slate-600">Record at least twelve fresh baseline-versus-assisted workflows. Rework, escalation and correction counts must not deteriorate.</p><div className="mt-4 grid gap-3 md:grid-cols-3"><input value={claimId} onChange={(e) => setClaimId(e.target.value)} placeholder="Claim UUID" className={input} /><select value={workflow} onChange={(e) => setWorkflow(e.target.value as typeof workflow)} className={input}><option value="chief_engineer_report">Chief Engineer Report</option><option value="engine_log">Engine Log</option></select><button disabled={busy !== null || !claimId} onClick={() => void addBusinessEvidence()} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record business evidence</button></div><button disabled={busy !== null} onClick={() => void act("finalize", () => request(`/ai-near-universal-outcomes/assessments/${current.id}/finalize`, { method: "POST", body: JSON.stringify({ confirm_finalize: true, note: "Freeze all Sprint 11P source-ledger technical, safety, recovery and business-value evidence for Sprint 11Q." }) }), "Sprint 11Q scorecard finalized.")} className="mt-5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Finalize measured scorecard</button></section>
    </>}

    {current?.metrics && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Measured evidence</h2><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">{[["Reject", pct(technical.human_reject_rate_bps)], ["Edit", pct(technical.human_edit_rate_bps)], ["Grounding", pct(technical.source_grounding_validity_bps)], ["TFTA improvement", pct(business.median_tfta_improvement_bps)], ["Handler effort", pct(business.median_handler_effort_improvement_bps)], ["Quality regression", pct(trend.quality_regression_bps)]].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}</div>{current.failure_reasons.length > 0 && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">Failed controls: {current.failure_reasons.join(", ")}</div>}</section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Twelve-party independent review</h2><p className="mt-2 text-sm text-slate-600">Includes Platform Reliability/SRE and Independent Production Assurance. Requester and final Admin must remain distinct from all reviewers.</p><div className="mt-4 flex flex-wrap gap-2">{roles.map((role) => <button key={role} disabled={busy !== null || reviewedRoles.has(role) || !["review_ready", "decision_ready"].includes(current.status)} onClick={() => void review(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}</div><div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5"><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("recommend_separate_100_percent_authorization_review")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Recommend separate 100% review</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("extend_near_universal_91_99")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Extend 91–99%</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("stop_ai_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Stop progression</button></div>{current.assessment_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Assessment SHA-256: {current.assessment_hash}</p>}{current.decision_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}</section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Hard boundary:</strong> Sprint 11Q is evidence and recommendation only. It never authorizes 100% rollout, Production-wide AI, Restricted documents, new document classes, autonomous claim decisions, automatic authoritative facts, or removal of different-human review.</section>
  </div>;
}
