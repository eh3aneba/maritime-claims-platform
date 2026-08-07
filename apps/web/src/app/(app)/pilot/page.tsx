"use client";

import { useEffect, useMemo, useState } from "react";

import { addPilotFeedback, endPilotSession, getPilotScorecard, listClaims, recordPilotBrowserEvent, startPilotSession } from "@/lib/api";
import type { Claim, PilotScorecard, PilotSession } from "@/lib/types";

const categories = ["usability", "ai_quality", "rules", "workflow", "feature_gap", "value", "missing_document", "technical", "financial"];

export default function PilotPage() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [claimId, setClaimId] = useState("");
  const [baseline, setBaseline] = useState("120");
  const [session, setSession] = useState<PilotSession | null>(null);
  const [scorecard, setScorecard] = useState<PilotScorecard | null>(null);
  const [category, setCategory] = useState("usability");
  const [severity, setSeverity] = useState("medium");
  const [verdict, setVerdict] = useState("");
  const [rating, setRating] = useState("8");
  const [comment, setComment] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    listClaims(new URLSearchParams({ limit: "100" })).then((result) => {
      setClaims(result.items);
      if (result.items[0]) setClaimId(result.items[0].id);
    });
  }, []);

  async function refreshScorecard(sessionId = session?.id) {
    if (!sessionId) return;
    setScorecard(await getPilotScorecard(sessionId));
  }

  async function start() {
    if (!claimId) return;
    const created = await startPilotSession({
      claim_id: claimId,
      participant_role: "claims_handler",
      objective: "Evaluate end-to-end H&M machinery claim workflow and decision-support value.",
      baseline_assessment_minutes: baseline ? Number(baseline) : null,
    });
    setSession(created);
    await recordPilotBrowserEvent(created.id, { event_type: "pilot_console_opened" });
    await refreshScorecard(created.id);
    setMessage("Pilot session active. Server-side claim actions will now be measured.");
  }

  async function submitFeedback() {
    if (!session || !comment.trim()) return;
    await addPilotFeedback(session.id, {
      category,
      severity,
      verdict: verdict || null,
      rating: rating ? Number(rating) : null,
      comment: comment.trim(),
    });
    setComment("");
    await refreshScorecard();
    setMessage("Feedback captured and added to the pilot backlog.");
  }

  async function finish() {
    if (!session) return;
    const closed = await endPilotSession(session.id, "completed", "Design-partner walkthrough completed.");
    setSession(closed);
    await refreshScorecard(closed.id);
    setMessage("Pilot session closed. Review the scorecard before planning the next pilot.");
  }

  const elapsed = useMemo(() => scorecard ? Math.round(scorecard.metrics.elapsed_seconds / 60) : 0, [scorecard]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Design partner instrumentation</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">Pilot session console</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">Measure real workflow outcomes. This console records feedback and scorecard metrics; it does not change claim decisions.</p>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="text-sm font-medium text-slate-700">Claim
            <select disabled={session?.status === "active"} value={claimId} onChange={(e) => setClaimId(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2">
              {claims.map((claim) => <option key={claim.id} value={claim.id}>{claim.claim_reference} · {claim.vessel.name}</option>)}
            </select>
          </label>
          <label className="text-sm font-medium text-slate-700">Manual baseline · minutes
            <input disabled={session?.status === "active"} value={baseline} onChange={(e) => setBaseline(e.target.value)} type="number" min="0" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <div className="flex items-end gap-2">
            {!session || session.status !== "active" ? <button onClick={start} className="rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white">Start pilot</button> : <button onClick={finish} className="rounded-lg bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white">End session</button>}
            {session && <button onClick={() => refreshScorecard()} className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold">Refresh</button>}
          </div>
        </div>
        {message && <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{message}</p>}
      </section>

      {scorecard && <>
        <section className="grid gap-4 md:grid-cols-4">
          <Metric title="Elapsed" value={`${elapsed} min`} />
          <Metric title="AI acceptance" value={scorecard.metrics.ai_acceptance_rate == null ? "—" : `${Math.round(scorecard.metrics.ai_acceptance_rate * 100)}%`} />
          <Metric title="Assessment time" value={scorecard.metrics.time_to_first_assessment_minutes == null ? "—" : `${scorecard.metrics.time_to_first_assessment_minutes} min`} />
          <Metric title="User rating" value={scorecard.metrics.average_rating == null ? "—" : `${scorecard.metrics.average_rating}/10`} />
        </section>

        <section className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="font-semibold">Capture feedback</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2">{categories.map((item) => <option key={item}>{item}</option>)}</select>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2"><option>low</option><option>medium</option><option>high</option><option>critical</option></select>
              <select value={verdict} onChange={(e) => setVerdict(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2"><option value="">No validation verdict</option><option value="correct">Correct</option><option value="true_positive">True positive</option><option value="false_positive">False positive</option><option value="false_negative">False negative / missed</option></select>
              <input value={rating} onChange={(e) => setRating(e.target.value)} type="number" min="1" max="10" className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Rating 1–10" />
            </div>
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={4} className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="What helped, failed, slowed you down, or would make you pay for this?" />
            <button onClick={submitFeedback} className="mt-3 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">Save feedback</button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between"><h2 className="font-semibold">Pilot scorecard</h2><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${scorecard.ready_for_next_pilot ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{scorecard.ready_for_next_pilot ? "Target pass" : "Learning in progress"}</span></div>
            <div className="mt-4 space-y-2 text-sm">
              {Object.entries(scorecard.checks).map(([key, value]) => <div key={key} className="flex justify-between border-b border-slate-100 py-2"><span>{key.replaceAll("_", " ")}</span><strong>{value == null ? "Not measured" : value ? "PASS" : "MISS"}</strong></div>)}
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="font-semibold">Feedback-generated backlog</h2>
          <div className="mt-4 space-y-3">
            {scorecard.backlog.length === 0 && <p className="text-sm text-slate-500">No feedback has been converted into backlog items yet.</p>}
            {scorecard.backlog.map((item) => <div key={item.feedback_id} className="flex gap-3 rounded-lg border border-slate-200 p-3"><span className="h-fit rounded-md bg-slate-900 px-2 py-1 text-xs font-bold text-white">{item.priority}</span><div><p className="text-sm font-semibold">{item.title}</p><p className="mt-1 text-xs text-slate-500">{item.category} · {item.rationale}</p></div></div>)}
          </div>
        </section>
      </>}
    </div>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</p><p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p></div>;
}
