"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type Run = {
  id: string;
  task_type: string;
  status: string;
  output_candidate_count: number | null;
};

type Authorization = {
  id: string;
  authorization_key: string;
  status: string;
  rollout_percentage: number;
  runs: Run[];
};

type Observation = {
  id: string;
  limited_run_id: string;
  workflow_type: string;
  usefulness_rating: number;
  review_seconds: number;
  unsupported_output_count: number;
  source_grounded_output_count: number;
  source_grounding_total_count: number;
  observation_hash: string;
};

type Review = { review_role: string; action: string };

type Assessment = {
  id: string;
  authorization_id: string;
  attempt_number: number;
  assessment_key: string;
  assessment_profile: string;
  rollout_percentage: number;
  status: string;
  metrics: Record<string, unknown> | null;
  failure_reasons: string[];
  assessment_hash: string | null;
  decision_hash: string | null;
  observations: Observation[];
  reviews: Review[];
  summary: {
    observation_count: number;
    graduation_stage_recommended: boolean;
    production_wide_authorized: boolean;
    restricted_documents_authorized: boolean;
    rollout_increase_authorized: boolean;
  };
};

type OutcomeDashboard = { assessments: Assessment[] };
type LimitedDashboard = { authorizations: Authorization[] };

const controlClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function percent(value: unknown) {
  return typeof value === "number" ? `${(value / 100).toFixed(2)}%` : "—";
}

function number(value: unknown, suffix = "") {
  return typeof value === "number" ? `${value}${suffix}` : "—";
}

function badge(status: string) {
  if (["review_ready", "decision_ready", "recommended"].includes(status)) {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }
  if (["review_rejected", "stopped"].includes(status)) {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

export default function AILimitedProductionOutcomesPage() {
  const [outcomes, setOutcomes] = useState<OutcomeDashboard | null>(null);
  const [limited, setLimited] = useState<LimitedDashboard | null>(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [usefulness, setUsefulness] = useState(5);
  const [reviewSeconds, setReviewSeconds] = useState(180);
  const [unsupported, setUnsupported] = useState(0);
  const [grounded, setGrounded] = useState(1);
  const [groundingTotal, setGroundingTotal] = useState(1);
  const [workflowCompleted, setWorkflowCompleted] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [outcomeData, limitedData] = await Promise.all([
        request<OutcomeDashboard>("/ai-limited-production-outcomes"),
        request<LimitedDashboard>("/ai-limited-production"),
      ]);
      setOutcomes(outcomeData);
      setLimited(limitedData);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load the Sprint 11F outcome gate.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const completed = limited?.authorizations.find((item) => item.status === "completed") ?? null;
  const current = outcomes?.assessments[0] ?? null;
  const observedRunIds = useMemo(
    () => new Set(current?.observations.map((item) => item.limited_run_id) ?? []),
    [current],
  );
  const unobservedRuns = completed?.runs.filter(
    (run) => run.status === "human_reviewed" && !observedRunIds.has(run.id),
  ) ?? [];

  useEffect(() => {
    if (!selectedRunId && unobservedRuns.length) {
      const run = unobservedRuns[0];
      const candidates = run.output_candidate_count ?? 1;
      setSelectedRunId(run.id);
      setGrounded(candidates);
      setGroundingTotal(candidates);
    }
  }, [selectedRunId, unobservedRuns]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try {
      await action();
      setMessage(success);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "The Sprint 11F action failed.");
    } finally {
      setBusy(null);
    }
  }

  async function create() {
    if (!completed) {
      setError("A completed Sprint 11E limited-production evaluation is required.");
      return;
    }
    await act(
      "create",
      () => request("/ai-limited-production-outcomes/assessments", {
        method: "POST",
        body: JSON.stringify({
          authorization_id: completed.id,
          assessment_key: `limited-production-outcome-${crypto.randomUUID()}`,
          confirm_content_free_assessment: true,
        }),
      }),
      "Sprint 11F content-free outcome assessment created.",
    );
  }

  async function observe(event: FormEvent) {
    event.preventDefault();
    if (!current || !selectedRunId) return;
    await act(
      "observe",
      () => request(
        `/ai-limited-production-outcomes/assessments/${current.id}/observations`,
        {
          method: "POST",
          body: JSON.stringify({
            limited_run_id: selectedRunId,
            usefulness_rating: usefulness,
            review_seconds: reviewSeconds,
            unsupported_output_count: unsupported,
            source_grounded_output_count: grounded,
            source_grounding_total_count: groundingTotal,
            workflow_completed: workflowCompleted,
            evidence_reference: `artifact://ai-limited-production-outcomes/run-${selectedRunId}`,
            note: "Operator recorded content-free usefulness, grounding and review-effort evidence for the reviewed Production-evaluation run.",
            confirm_content_free_observation: true,
          }),
        },
      ),
      "Immutable content-free run observation recorded.",
    );
    setSelectedRunId("");
  }

  async function review(role: "product" | "quality" | "risk" | "operations") {
    if (!current) return;
    await act(
      `review-${role}`,
      () => request(`/ai-limited-production-outcomes/assessments/${current.id}/reviews`, {
        method: "POST",
        body: JSON.stringify({
          review_role: role,
          action: "approve",
          evidence_reference: `artifact://ai-limited-production-outcomes/${role}-review`,
          note: `Independent ${role} reviewer reproduced the fixed Sprint 11F scorecard and safety boundaries.`,
        }),
      }),
      `${role} review recorded.`,
    );
  }

  async function decide(outcome: "recommend_graduation_stage" | "extend_limited_production_evaluation" | "stop_ai_progression") {
    if (!current) return;
    await act(
      `decision-${outcome}`,
      () => request(`/ai-limited-production-outcomes/assessments/${current.id}/decision`, {
        method: "POST",
        body: JSON.stringify({
          outcome,
          confirm_recommendation_only: true,
          note: outcome === "recommend_graduation_stage"
            ? "Administrator recommends designing a separate graduation authorization; no rollout expands in Sprint 11F."
            : outcome === "extend_limited_production_evaluation"
              ? "Administrator requires another bounded limited-production evaluation before any graduation design."
              : "Administrator stops AI progression; no wider Production authorization is granted.",
        }),
      }),
      "Recommendation-only Sprint 11F decision recorded.",
    );
  }

  const metrics = current?.metrics ?? {};
  const reviewedRoles = new Set(current?.reviews.map((item) => item.review_role) ?? []);
  const canCreate = completed && (!current || current.authorization_id !== completed.id
    || ["review_rejected", "extended", "stopped"].includes(current.status));

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11F · measured limited-production exit</p>
      <h1 className="mt-3 text-3xl font-semibold">Limited-production outcome & graduation gate</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Freeze the completed 11E cohort, measure human review, usefulness, unsupported output, source grounding, latency, cost and second-half regression, then require independent Product, Quality, Risk and Operations review. A positive result is still only a recommendation for a separate future authorization.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Assessment", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Observed runs", current ? `${current.summary.observation_count}/${number(metrics.run_count)}` : "0/—"],
        ["Source grounding", percent(metrics.source_grounding_validity_bps)],
        ["Rollout expansion", "Not authorized"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize text-slate-900">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Start a Sprint 11F assessment</h2>
      <p className="mt-2 text-sm text-slate-600">Anchor: completed 11E authorization {completed?.authorization_key}. The exact model bundle and recorded rollout percentage are frozen into the assessment.</p>
      <button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create outcome assessment</button>
    </section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {current.attempt_number} · rollout {current.rollout_percentage}%</p><h2 className="mt-1 text-xl font-semibold">{current.assessment_key}</h2></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${badge(current.status)}`}>{current.status.replaceAll("_", " ")}</span></div>
      {current.metrics && <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{[
        ["Human review", percent(metrics.human_review_rate_bps)],
        ["Reject", percent(metrics.human_reject_rate_bps)],
        ["Edit", percent(metrics.human_edit_rate_bps)],
        ["Unsupported", percent(metrics.unsupported_output_rate_bps)],
        ["Grounding", percent(metrics.source_grounding_validity_bps)],
        ["Usefulness", percent(metrics.mean_usefulness_bps)],
        ["Review effort", number(metrics.mean_review_seconds, "s")],
        ["P95 latency", number(metrics.p95_latency_ms, "ms")],
        ["Mean cost", number(metrics.mean_observed_provider_cost_microusd, " μUSD")],
        ["Second-half regression", (metrics.trend as { material_regression?: boolean } | undefined)?.material_regression ? "Material" : "No material"],
      ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}</div>}
      {current.failure_reasons.length > 0 && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">Failed controls: {current.failure_reasons.join(", ")}</div>}
      <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
        <button disabled={busy !== null || current.status !== "collecting"} onClick={() => void act("finalize", () => request(`/ai-limited-production-outcomes/assessments/${current.id}/finalize`, { method: "POST", body: JSON.stringify({ confirm_finalize: true, note: "Operator froze the complete reviewed cohort and deterministic 11F scorecard." }) }), "Outcome scorecard finalized and frozen.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Finalize scorecard</button>
        {(["product", "quality", "risk", "operations"] as const).map((role) => <button key={role} disabled={busy !== null || reviewedRoles.has(role) || !["review_ready", "decision_ready"].includes(current.status)} onClick={() => void review(role)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role} approve</button>)}
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("recommend_graduation_stage")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Recommend graduation design</button>
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("extend_limited_production_evaluation")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Extend evaluation</button>
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("stop_ai_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Stop progression</button>
      </div>
      {current.assessment_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Assessment SHA-256: {current.assessment_hash}</p>}
      {current.decision_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}
    </section>}

    {current?.status === "collecting" && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Record content-free run evidence</h2>
      <p className="mt-2 text-sm text-slate-600">Do not paste claim text, prompts, provider responses or source quotes. Record only bounded observations linked to the immutable reviewed run.</p>
      <form onSubmit={observe} className="mt-5 space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs font-semibold text-slate-600">Reviewed run<select required value={selectedRunId} onChange={(event) => { const id = event.target.value; setSelectedRunId(id); const candidates = unobservedRuns.find((run) => run.id === id)?.output_candidate_count ?? 1; setGrounded(candidates); setGroundingTotal(candidates); }} className={`mt-1 ${controlClass}`}><option value="">Select unobserved run</option>{unobservedRuns.map((run) => <option key={run.id} value={run.id}>{run.task_type.replaceAll("_", " ")} · {run.id}</option>)}</select></label>
          <label className="text-xs font-semibold text-slate-600">Usefulness (1–5)<input type="number" min={1} max={5} value={usefulness} onChange={(event) => setUsefulness(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
          <label className="text-xs font-semibold text-slate-600">Review seconds<input type="number" min={1} max={3600} value={reviewSeconds} onChange={(event) => setReviewSeconds(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
          <label className="text-xs font-semibold text-slate-600">Unsupported outputs<input type="number" min={0} value={unsupported} onChange={(event) => setUnsupported(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
          <label className="text-xs font-semibold text-slate-600">Grounded outputs<input type="number" min={0} value={grounded} onChange={(event) => setGrounded(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
          <label className="text-xs font-semibold text-slate-600">Grounding total<input type="number" min={0} value={groundingTotal} onChange={(event) => setGroundingTotal(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={workflowCompleted} onChange={(event) => setWorkflowCompleted(event.target.checked)} /> Workflow completed</label>
        <button disabled={busy !== null || !selectedRunId} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record immutable observation</button>
      </form>
    </section>}

    <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900"><strong>Hard boundary:</strong> Sprint 11F never increases rollout, authorizes Production-wide use, admits Restricted documents or new document classes, or permits autonomous claim decisions. A positive result only recommends designing another separately authorized stage.</section>
  </div>;
}
