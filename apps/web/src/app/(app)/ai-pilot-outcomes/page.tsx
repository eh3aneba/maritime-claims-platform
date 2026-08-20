"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError, createAIPilotOutcomeAssessment, decideAIPilotOutcome,
  finalizeAIPilotOutcomeAssessment, getAIPilotOutcomes, getAIPrivatePilot,
  recordAIPilotWorkflowObservation, reviewAIPilotOutcomeAssessment,
} from "@/lib/api";
import type {
  AIPilotOutcomeAssessment, AIPilotOutcomeDashboard, AIPrivatePilotDashboard,
} from "@/lib/types";

const controlClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

function badge(status: string) {
  if (["review_ready", "decision_ready", "recommended"].includes(status)) {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }
  if (["failed", "review_rejected", "stopped"].includes(status)) {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function Badge({ value }: { value: string }) {
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${badge(value)}`}>{value.replaceAll("_", " ")}</span>;
}

function metric(item: AIPilotOutcomeAssessment | null, key: string) {
  const value = item?.metrics?.[key];
  return typeof value === "number" ? value : null;
}

function percent(value: number | null) {
  return value === null ? "—" : `${(value / 100).toFixed(2)}%`;
}

export default function AIPilotOutcomesPage() {
  const [outcomes, setOutcomes] = useState<AIPilotOutcomeDashboard | null>(null);
  const [pilots, setPilots] = useState<AIPrivatePilotDashboard | null>(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [usefulness, setUsefulness] = useState(5);
  const [reviewSeconds, setReviewSeconds] = useState(180);
  const [workflowCompleted, setWorkflowCompleted] = useState(true);
  const [boundaryPassed, setBoundaryPassed] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [outcomeData, pilotData] = await Promise.all([
        getAIPilotOutcomes(), getAIPrivatePilot(),
      ]);
      setOutcomes(outcomeData); setPilots(pilotData); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load the private-pilot outcome gate.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const completedPilot = pilots?.pilots.find((item) => item.status === "completed") ?? null;
  const current = outcomes?.assessments[0] ?? null;
  const observedRunIds = useMemo(
    () => new Set(current?.observations.map((item) => item.pilot_run_id) ?? []), [current]);
  const unobservedRuns = completedPilot?.runs.filter(
    (run) => run.status === "human_reviewed" && !observedRunIds.has(run.id)) ?? [];
  const canCreate = completedPilot && (!current || current.pilot_id !== completedPilot.id
    || ["failed", "review_rejected", "extended", "stopped"].includes(current.status));

  useEffect(() => {
    if (!selectedRunId && unobservedRuns.length) setSelectedRunId(unobservedRuns[0].id);
  }, [selectedRunId, unobservedRuns]);

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "The pilot-outcome action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!completedPilot) { setError("A completed Sprint 11C private pilot is required."); return; }
    await run("create", () => createAIPilotOutcomeAssessment(completedPilot.id),
      "A content-free Sprint 11D assessment attempt was created.");
  }

  async function record(event: FormEvent) {
    event.preventDefault();
    if (!current || !selectedRunId) return;
    await run("observation", () => recordAIPilotWorkflowObservation(current.id, {
      pilot_run_id: selectedRunId, usefulness_rating: usefulness,
      review_seconds: reviewSeconds, workflow_completed: workflowCompleted,
      boundary_control_passed: boundaryPassed,
      evidence_reference: `artifact://ai-pilot-outcomes/run-${selectedRunId}`,
      note: "Operator recorded content-free workflow usefulness, effort and boundary evidence for this reviewed pilot run.",
    }), "Immutable per-workflow observation recorded without claim or provider content.");
    setSelectedRunId("");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11D · measured pilot exit</p>
      <h1 className="mt-3 text-3xl font-semibold">Private-pilot outcome scorecard</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Measure every reviewed CE Report and Engine Log run, freeze usability, human-action, latency, cost and incident trends, then require independent Product, Quality and Risk review. The final result is only an exit recommendation—not production authorization.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Assessment", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Observed runs", current ? `${current.summary.observation_count}/${metric(current, "run_count") ?? "—"}` : "0/—"],
        ["Usefulness", percent(metric(current, "mean_usefulness_bps"))],
        ["Production authorized", "No"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize text-slate-900">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Start a fixed-threshold exit assessment</h2>
      <p className="mt-2 text-sm text-slate-600">Completed pilot: {completedPilot?.pilot_key}. Minimum sample: 6 reviewed runs, including 3 CE Reports and 3 Engine Logs.</p>
      <button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create outcome assessment</button>
    </section>}

    {current && <AssessmentControl item={current} busy={busy} run={run} />}

    {current?.status === "collecting" && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Record one reviewed workflow observation</h2>
      <p className="mt-2 text-sm text-slate-600">Run identity, workflow type, cost and latency remain anchored to the immutable Sprint 11C ledger. Enter only content-free usability evidence.</p>
      <form onSubmit={record} className="mt-5 space-y-4">
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs font-semibold text-slate-600">Reviewed run<select required value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)} className={`mt-1 ${controlClass}`}><option value="">Select unobserved run</option>{unobservedRuns.map((run) => <option key={run.id} value={run.id}>{run.task_type.replaceAll("_", " ")} · {run.id}</option>)}</select></label>
          <label className="text-xs font-semibold text-slate-600">Usefulness (1–5)<input type="number" min={1} max={5} value={usefulness} onChange={(event) => setUsefulness(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
          <label className="text-xs font-semibold text-slate-600">Human review seconds<input type="number" min={1} max={3600} value={reviewSeconds} onChange={(event) => setReviewSeconds(Number(event.target.value))} className={`mt-1 ${controlClass}`} /></label>
        </div>
        <div className="flex flex-wrap gap-5 text-sm"><label className="flex items-center gap-2"><input type="checkbox" checked={workflowCompleted} onChange={(event) => setWorkflowCompleted(event.target.checked)} /> Workflow completed</label><label className="flex items-center gap-2"><input type="checkbox" checked={boundaryPassed} onChange={(event) => setBoundaryPassed(event.target.checked)} /> Safety boundary passed</label></div>
        <button disabled={busy !== null || !selectedRunId} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record immutable observation</button>
      </form>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Content-free workflow evidence</h2>
      <div className="mt-4 space-y-2">{current?.observations.length ? current.observations.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.workflow_type.replaceAll("_", " ")} · usefulness {item.usefulness_rating}/5</p><p className="mt-1 text-xs text-slate-500">{item.review_seconds}s review · run {item.pilot_run_id} · SHA-256 {item.observation_hash.slice(0, 12)}…</p></div><Badge value={item.boundary_control_passed && item.workflow_completed ? "pass" : "fail"} /></div>) : <p className="text-sm text-slate-500">No workflow observation recorded.</p>}</div>
    </section>

    <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900"><strong>Hard boundary:</strong> “recommend limited-production evaluation” means only that a separate later authorization may be designed and reviewed. It does not enable Production, broaden the cohort, admit Restricted documents, or make any autonomous claim decision. Full English/Persian UI localization remains deferred.</section>
  </div>;
}

function AssessmentControl({ item, busy, run }: { item: AIPilotOutcomeAssessment; busy: string | null; run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void> }) {
  const reviewed = new Set(item.reviews.map((review) => review.review_role));
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {item.attempt_number} · {item.assessment_profile}</p><h2 className="mt-1 text-xl font-semibold">{item.assessment_key}</h2><p className="mt-1 text-xs text-slate-500">Pilot {item.pilot_id}</p></div><Badge value={item.status} /></div>
    {item.metrics && <div className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">{[
      ["Review coverage", percent(metric(item, "human_review_rate_bps"))],
      ["Reject rate", percent(metric(item, "human_reject_rate_bps"))],
      ["Edit rate", percent(metric(item, "human_edit_rate_bps"))],
      ["Usefulness", percent(metric(item, "mean_usefulness_bps"))],
      ["Review time", `${metric(item, "mean_review_seconds") ?? "—"}s`],
      ["P95 latency", `${metric(item, "p95_latency_ms") ?? "—"}ms`],
    ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}</div>}
    {item.failure_reasons.length > 0 && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">Failed controls: {item.failure_reasons.join(", ")}</div>}
    <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
      <button disabled={busy !== null || item.status !== "collecting"} onClick={() => void run("finalize", () => finalizeAIPilotOutcomeAssessment(item.id), "Outcome scorecard finalized and frozen.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Finalize scorecard</button>
      {(["product", "quality", "risk"] as const).map((role) => <button key={role} disabled={busy !== null || reviewed.has(role) || !["review_ready", "decision_ready"].includes(item.status)} onClick={() => void run(`review-${role}`, () => reviewAIPilotOutcomeAssessment(item.id, role, "approve"), `${role} review recorded.`)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role} approve</button>)}
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("recommend", () => decideAIPilotOutcome(item.id, "recommend_limited_production_evaluation"), "Recommendation recorded; Production remains unauthorized.")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Recommend separate evaluation</button>
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("extend", () => decideAIPilotOutcome(item.id, "extend_private_pilot"), "A new bounded pilot attempt is required.")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Extend pilot</button>
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("stop", () => decideAIPilotOutcome(item.id, "stop_ai_progression"), "AI progression stopped.")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Stop progression</button>
    </div>
    <p className="mt-3 text-xs text-slate-500">Requester and Product/Quality/Risk reviewers must be four different people. Only Admin records the final recommendation.</p>
    {item.assessment_hash && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Assessment SHA-256: {item.assessment_hash}</p>}
    {item.decision_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {item.decision_hash}</p>}
  </section>;
}
