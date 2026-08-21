"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";

type BroaderRun = { id: string; task_type: string; status: string };
type BroaderAuthorization = { id: string; authorization_key: string; status: string; rollout_percentage: number; runs: BroaderRun[] };
type Observation = { broader_production_run_id: string; usefulness_rating: number; review_seconds: number };
type Review = { review_role: string; action: string };
type Assessment = {
  id: string; broader_production_authorization_id: string; assessment_key: string; attempt_number: number;
  status: string; rollout_percentage: number; metrics: Record<string, unknown> | null;
  failure_reasons: string[]; assessment_hash: string | null; decision_hash: string | null;
  observations: Observation[]; reviews: Review[];
  summary: { next_broader_stage_recommended: boolean; production_wide_authorized: boolean; rollout_above_50_authorized: boolean };
};
type OutcomeDashboard = { assessments: Assessment[] };
type BroaderDashboard = { authorizations: BroaderAuthorization[] };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init, credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

const control = "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const pct = (value: unknown) => typeof value === "number" ? `${(value / 100).toFixed(2)}%` : "—";
const num = (value: unknown, suffix = "") => typeof value === "number" ? `${value}${suffix}` : "—";

export default function AIBroaderProductionOutcomesPage() {
  const [outcomes, setOutcomes] = useState<OutcomeDashboard | null>(null);
  const [broader, setBroader] = useState<BroaderDashboard | null>(null);
  const [runId, setRunId] = useState("");
  const [usefulness, setUsefulness] = useState(5);
  const [reviewSeconds, setReviewSeconds] = useState(150);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<OutcomeDashboard>("/ai-broader-production-outcomes"),
        request<BroaderDashboard>("/ai-broader-production"),
      ]);
      setOutcomes(a); setBroader(b); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11J.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const completed = broader?.authorizations.find((item) => item.status === "completed") ?? null;
  const current = outcomes?.assessments[0] ?? null;
  const observed = useMemo(() => new Set(current?.observations.map((item) => item.broader_production_run_id) ?? []), [current]);
  const pendingRuns = completed?.runs.filter((run) => run.status === "human_reviewed" && !observed.has(run.id)) ?? [];
  useEffect(() => { if (!runId && pendingRuns.length) setRunId(pendingRuns[0].id); }, [runId, pendingRuns]);

  async function act(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11J action failed."); }
    finally { setBusy(false); }
  }

  async function create() {
    if (!completed) return setError("A completed Sprint 11I broader-production cohort is required.");
    await act(() => request("/ai-broader-production-outcomes/assessments", {
      method: "POST", body: JSON.stringify({
        broader_production_authorization_id: completed.id,
        assessment_key: `broader-readiness-${crypto.randomUUID()}`,
        confirm_content_free_assessment: true,
      }),
    }), "Sprint 11J readiness assessment created.");
  }

  async function observe() {
    if (!current || !runId) return;
    await act(() => request(`/ai-broader-production-outcomes/assessments/${current.id}/observations`, {
      method: "POST", body: JSON.stringify({
        broader_production_run_id: runId, usefulness_rating: usefulness, review_seconds: reviewSeconds,
        workflow_completed: true,
        evidence_reference: `artifact://ai-broader-production-outcomes/run-${runId}`,
        note: "Content-free usefulness and operator-effort evidence for the immutable Sprint 11I run.",
        confirm_content_free_observation: true,
      }),
    }), "Run observation recorded.");
    setRunId("");
  }

  async function review(role: "product" | "quality" | "risk" | "operations" | "security" | "claims_governance") {
    if (!current) return;
    await act(() => request(`/ai-broader-production-outcomes/assessments/${current.id}/reviews`, {
      method: "POST", body: JSON.stringify({ review_role: role, action: "approve",
        evidence_reference: `artifact://ai-broader-production-outcomes/${role}-review`,
        note: `Independent ${role} reviewer reproduced the frozen Sprint 11J scorecard.` }),
    }), `${role} review recorded.`);
  }

  async function decide(outcome: "recommend_next_broader_stage" | "extend_broader_production" | "stop_ai_progression") {
    if (!current) return;
    await act(() => request(`/ai-broader-production-outcomes/assessments/${current.id}/decision`, {
      method: "POST", body: JSON.stringify({ outcome, confirm_recommendation_only: true,
        note: outcome === "recommend_next_broader_stage"
          ? "Recommend only designing a separately authorized next stage; no >50% rollout is granted here."
          : outcome === "extend_broader_production"
            ? "Require another bounded 26–50% cohort before any next-stage design."
            : "Stop AI progression without granting broader permissions." }),
    }), "Recommendation-only Sprint 11J decision recorded.");
  }

  const metrics = current?.metrics ?? {};
  const roles = new Set(current?.reviews.map((review) => review.review_role) ?? []);
  const canCreate = completed && (!current || current.broader_production_authorization_id !== completed.id || ["review_rejected", "extended", "stopped"].includes(current.status));

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11J · broader-production outcome</p>
      <h1 className="mt-3 text-3xl font-semibold">&gt;50% readiness recommendation gate</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Measure the completed 26–50% Sprint 11I cohort using immutable run, monitor, incident and recovery evidence. Six independent reviews are required. Even a passing result grants no rollout above 50%, Production-wide authorization, Restricted documents or autonomous claim decisions.</p>
    </section>

    {(message || error) && <div className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Assessment", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Observed runs", current ? `${current.observations.length}/${num(metrics.run_count)}` : "0/—"],
        ["Grounding", pct(metrics.source_grounding_validity_bps)],
        ["Rollout >50%", "Not authorized"]].map(([label, value]) =>
        <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Start Sprint 11J</h2>
      <p className="mt-2 text-sm text-slate-600">Anchor the completed Sprint 11I authorization and freeze its exact decision hash plus inherited 11H/11G/11F hashes.</p>
      <button disabled={busy} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create readiness assessment</button>
    </section>}

    {current?.status === "collecting" && pendingRuns.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Record content-free operator outcome</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <select value={runId} onChange={(e) => setRunId(e.target.value)} className={control}>{pendingRuns.map((run) => <option key={run.id} value={run.id}>{run.task_type} · {run.id.slice(0, 8)}</option>)}</select>
        <input type="number" min={1} max={5} value={usefulness} onChange={(e) => setUsefulness(Number(e.target.value))} className={control} />
        <input type="number" min={1} max={3600} value={reviewSeconds} onChange={(e) => setReviewSeconds(Number(e.target.value))} className={control} />
        <button disabled={busy || !runId} onClick={() => void observe()} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record observation</button>
      </div>
    </section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs uppercase text-slate-500">Attempt {current.attempt_number} · rollout {current.rollout_percentage}%</p><h2 className="mt-1 text-xl font-semibold">{current.assessment_key}</h2></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{current.status.replaceAll("_", " ")}</span></div>
      {current.metrics && <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{[
        ["Reviewed runs", num(metrics.human_reviewed_run_count)], ["Reject", pct(metrics.human_reject_rate_bps)],
        ["Edit", pct(metrics.human_edit_rate_bps)], ["Unsupported", pct(metrics.unsupported_output_rate_bps)],
        ["Grounding", pct(metrics.source_grounding_validity_bps)], ["Usefulness", pct(metrics.mean_usefulness_bps)],
        ["Review effort", num(metrics.mean_review_seconds, "s")], ["P95 latency", num(metrics.p95_latency_ms, "ms")],
        ["Mean cost", num(metrics.mean_observed_provider_cost_microusd, " μUSD")],
        ["Pause recovery", pct((metrics.rollback_recovery as { recovery_rate_bps?: number } | undefined)?.recovery_rate_bps)],
      ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}</div>}
      {current.failure_reasons.length > 0 && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">Failed controls: {current.failure_reasons.join(", ")}</div>}
      <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
        <button disabled={busy || current.status !== "collecting"} onClick={() => void act(() => request(`/ai-broader-production-outcomes/assessments/${current.id}/finalize`, { method: "POST", body: JSON.stringify({ confirm_finalize: true, note: "Freeze the complete Sprint 11I cohort, monitoring, incident and recovery evidence." }) }), "Sprint 11J scorecard finalized.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Finalize scorecard</button>
        {(["product", "quality", "risk", "operations", "security", "claims_governance"] as const).map((role) => <button key={role} disabled={busy || roles.has(role) || !["review_ready", "decision_ready"].includes(current.status)} onClick={() => void review(role)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}
        <button disabled={busy || current.status !== "decision_ready"} onClick={() => void decide("recommend_next_broader_stage")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Recommend next-stage design</button>
        <button disabled={busy || current.status !== "decision_ready"} onClick={() => void decide("extend_broader_production")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Extend 26–50% cohort</button>
        <button disabled={busy || current.status !== "decision_ready"} onClick={() => void decide("stop_ai_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Stop progression</button>
      </div>
      {current.assessment_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Assessment SHA-256: {current.assessment_hash}</p>}
      {current.decision_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}
    </section>}
  </div>;
}
