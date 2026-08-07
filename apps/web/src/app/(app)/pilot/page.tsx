"use client";

import { useEffect, useMemo, useState } from "react";

import {
  addPilotFeedback,
  endPilotSession,
  getPilotCommercialScorecard,
  getPilotScorecard,
  listClaims,
  recordPilotBrowserEvent,
  savePilotCommercialValidation,
  startPilotSession,
} from "@/lib/api";
import type { Claim, PilotCommercialScorecard, PilotScorecard, PilotSession } from "@/lib/types";

const categories = ["usability", "ai_quality", "rules", "workflow", "feature_gap", "value", "missing_document", "technical", "financial"];

type CommercialForm = {
  annual_claim_volume: string;
  fully_loaded_hourly_cost: string;
  adoption_rate: string;
  expected_users: string;
  buyer_role: string;
  champion_role: string;
  budget_owner_role: string;
  budget_status: string;
  buying_stage: string;
  pilot_fee_willingness: string;
  annual_wtp_min: string;
  annual_wtp_max: string;
  preferred_pricing_model: string;
  deployment_preference: string;
  respondent_outcome: string;
  decision_timeline_days: string;
  must_have_features: string;
  blockers: string;
  security_requirements: string;
  next_step: string;
  commercial_notes: string;
};

const emptyCommercial: CommercialForm = {
  annual_claim_volume: "",
  fully_loaded_hourly_cost: "",
  adoption_rate: "0.5",
  expected_users: "",
  buyer_role: "",
  champion_role: "",
  budget_owner_role: "",
  budget_status: "unknown",
  buying_stage: "problem_validation",
  pilot_fee_willingness: "",
  annual_wtp_min: "",
  annual_wtp_max: "",
  preferred_pricing_model: "unknown",
  deployment_preference: "unknown",
  respondent_outcome: "unknown",
  decision_timeline_days: "",
  must_have_features: "",
  blockers: "",
  security_requirements: "",
  next_step: "",
  commercial_notes: "",
};

function optionalNumber(value: string) {
  return value.trim() === "" ? null : Number(value);
}
function csv(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export default function PilotPage() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [claimId, setClaimId] = useState("");
  const [baseline, setBaseline] = useState("120");
  const [session, setSession] = useState<PilotSession | null>(null);
  const [scorecard, setScorecard] = useState<PilotScorecard | null>(null);
  const [commercialScorecard, setCommercialScorecard] = useState<PilotCommercialScorecard | null>(null);
  const [commercial, setCommercial] = useState<CommercialForm>(emptyCommercial);
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

  async function refreshScorecards(sessionId = session?.id) {
    if (!sessionId) return;
    const [product, commercialResult] = await Promise.all([
      getPilotScorecard(sessionId),
      getPilotCommercialScorecard(sessionId),
    ]);
    setScorecard(product);
    setCommercialScorecard(commercialResult);
  }

  async function start() {
    if (!claimId) return;
    const created = await startPilotSession({
      claim_id: claimId,
      participant_role: "claims_handler",
      objective: "Evaluate end-to-end H&M machinery claim workflow, measurable value, and commercial buying signals.",
      baseline_assessment_minutes: baseline ? Number(baseline) : null,
    });
    setSession(created);
    await recordPilotBrowserEvent(created.id, { event_type: "pilot_console_opened" });
    await refreshScorecards(created.id);
    setMessage("Pilot session active. Product actions and commercial discovery can now be recorded against the same session.");
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
    await refreshScorecards();
    setMessage("Feedback captured and added to the pilot backlog.");
  }

  async function saveCommercial() {
    if (!session) return;
    await savePilotCommercialValidation(session.id, {
      annual_claim_volume: optionalNumber(commercial.annual_claim_volume),
      fully_loaded_hourly_cost: optionalNumber(commercial.fully_loaded_hourly_cost),
      adoption_rate: optionalNumber(commercial.adoption_rate),
      expected_users: optionalNumber(commercial.expected_users),
      currency: "USD",
      buyer_role: commercial.buyer_role || null,
      champion_role: commercial.champion_role || null,
      budget_owner_role: commercial.budget_owner_role || null,
      procurement_owner_role: null,
      security_approver_role: null,
      budget_status: commercial.budget_status,
      buying_stage: commercial.buying_stage,
      decision_timeline_days: optionalNumber(commercial.decision_timeline_days),
      pilot_fee_willingness: optionalNumber(commercial.pilot_fee_willingness),
      annual_wtp_min: optionalNumber(commercial.annual_wtp_min),
      annual_wtp_max: optionalNumber(commercial.annual_wtp_max),
      preferred_pricing_model: commercial.preferred_pricing_model,
      deployment_preference: commercial.deployment_preference,
      value_hypotheses: ["reduce claim review time", "improve auditability"],
      must_have_features: csv(commercial.must_have_features),
      required_integrations: [],
      security_requirements: csv(commercial.security_requirements),
      blockers: csv(commercial.blockers),
      respondent_outcome: commercial.respondent_outcome,
      next_step: commercial.next_step || null,
      next_step_due_date: null,
      commercial_notes: commercial.commercial_notes || null,
    });
    await refreshScorecards();
    setMessage("Commercial validation saved. Treat ROI and GO/PIVOT/STOP as pilot decision support, not as a forecast or sales commitment.");
  }

  async function finish() {
    if (!session) return;
    const closed = await endPilotSession(session.id, "completed", "Design-partner walkthrough and commercial interview completed.");
    setSession(closed);
    await refreshScorecards(closed.id);
    setMessage("Pilot session closed. Review both product and commercial scorecards before choosing the next validation step.");
  }

  const elapsed = useMemo(() => scorecard ? Math.round(scorecard.metrics.elapsed_seconds / 60) : 0, [scorecard]);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Design partner validation</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">Pilot & commercial validation console</h1>
        <p className="mt-2 max-w-4xl text-sm text-slate-600">Measure workflow outcomes, capture buying evidence, and leave each session with an explicit next validation decision. These records never alter claim decisions.</p>
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
            {session && <button onClick={() => refreshScorecards()} className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold">Refresh</button>}
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
            <h2 className="font-semibold">Capture product feedback</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2">{categories.map((item) => <option key={item}>{item}</option>)}</select>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2"><option>low</option><option>medium</option><option>high</option><option>critical</option></select>
              <select value={verdict} onChange={(e) => setVerdict(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2"><option value="">No validation verdict</option><option value="correct">Correct</option><option value="true_positive">True positive</option><option value="false_positive">False positive</option><option value="false_negative">False negative / missed</option></select>
              <input value={rating} onChange={(e) => setRating(e.target.value)} type="number" min="1" max="10" className="rounded-lg border border-slate-300 px-3 py-2" placeholder="Rating 1–10" />
            </div>
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={4} className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="What helped, failed, slowed you down, or would create value?" />
            <button onClick={submitFeedback} className="mt-3 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">Save feedback</button>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between"><h2 className="font-semibold">Product scorecard</h2><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${scorecard.ready_for_next_pilot ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{scorecard.ready_for_next_pilot ? "Target pass" : "Learning in progress"}</span></div>
            <div className="mt-4 space-y-2 text-sm">
              {Object.entries(scorecard.checks).map(([key, value]) => <div key={key} className="flex justify-between border-b border-slate-100 py-2"><span>{key.replaceAll("_", " ")}</span><strong>{value == null ? "Not measured" : value ? "PASS" : "MISS"}</strong></div>)}
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><h2 className="font-semibold">Commercial interview</h2><p className="mt-1 text-sm text-slate-500">Record buying evidence, not compliments. Unknown fields should stay unknown.</p></div>
            <button disabled={!session} onClick={saveCommercial} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Save commercial validation</button>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-3">
            <Field label="Annual relevant claims" value={commercial.annual_claim_volume} onChange={(v) => setCommercial({...commercial, annual_claim_volume:v})} type="number" />
            <Field label="Loaded hourly cost · USD" value={commercial.fully_loaded_hourly_cost} onChange={(v) => setCommercial({...commercial, fully_loaded_hourly_cost:v})} type="number" />
            <Field label="Expected adoption rate · 0–1" value={commercial.adoption_rate} onChange={(v) => setCommercial({...commercial, adoption_rate:v})} type="number" />
            <Field label="Buyer role" value={commercial.buyer_role} onChange={(v) => setCommercial({...commercial, buyer_role:v})} />
            <Field label="Champion role" value={commercial.champion_role} onChange={(v) => setCommercial({...commercial, champion_role:v})} />
            <Field label="Budget owner role" value={commercial.budget_owner_role} onChange={(v) => setCommercial({...commercial, budget_owner_role:v})} />
            <SelectField label="Budget status" value={commercial.budget_status} onChange={(v) => setCommercial({...commercial, budget_status:v})} options={["unknown","no_budget","exploring","budget_identified","approved"]} />
            <SelectField label="Buying stage" value={commercial.buying_stage} onChange={(v) => setCommercial({...commercial, buying_stage:v})} options={["problem_validation","solution_evaluation","pilot","business_case","procurement","contracting","no_interest"]} />
            <Field label="Decision timeline · days" value={commercial.decision_timeline_days} onChange={(v) => setCommercial({...commercial, decision_timeline_days:v})} type="number" />
            <Field label="Paid pilot willingness · USD" value={commercial.pilot_fee_willingness} onChange={(v) => setCommercial({...commercial, pilot_fee_willingness:v})} type="number" />
            <Field label="Annual WTP minimum · USD" value={commercial.annual_wtp_min} onChange={(v) => setCommercial({...commercial, annual_wtp_min:v})} type="number" />
            <Field label="Annual WTP maximum · USD" value={commercial.annual_wtp_max} onChange={(v) => setCommercial({...commercial, annual_wtp_max:v})} type="number" />
            <SelectField label="Pricing preference" value={commercial.preferred_pricing_model} onChange={(v) => setCommercial({...commercial, preferred_pricing_model:v})} options={["unknown","pilot_fee","annual_platform","per_user","per_claim","usage"]} />
            <SelectField label="Deployment preference" value={commercial.deployment_preference} onChange={(v) => setCommercial({...commercial, deployment_preference:v})} options={["unknown","cloud","private_cloud","on_prem"]} />
            <SelectField label="Respondent outcome" value={commercial.respondent_outcome} onChange={(v) => setCommercial({...commercial, respondent_outcome:v})} options={["unknown","interested","pilot_extension","business_case","procurement","no_interest"]} />
            <Field label="Must-have features · comma separated" value={commercial.must_have_features} onChange={(v) => setCommercial({...commercial, must_have_features:v})} />
            <Field label="Security requirements · comma separated" value={commercial.security_requirements} onChange={(v) => setCommercial({...commercial, security_requirements:v})} />
            <Field label="Blockers · comma separated" value={commercial.blockers} onChange={(v) => setCommercial({...commercial, blockers:v})} />
          </div>
          <textarea value={commercial.next_step} onChange={(e) => setCommercial({...commercial, next_step:e.target.value})} rows={2} className="mt-4 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="Concrete next step: e.g. security review + paid pilot proposal with named owner." />
          <textarea value={commercial.commercial_notes} onChange={(e) => setCommercial({...commercial, commercial_notes:e.target.value})} rows={3} className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2" placeholder="Buying process, objections, procurement notes, pricing language used by the respondent." />
        </section>

        {commercialScorecard && <section className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">Commercial validation decision</h2><DecisionBadge decision={commercialScorecard.recommended_validation_decision} /></div>
            <div className="mt-4 space-y-2 text-sm">
              {Object.entries(commercialScorecard.checks).map(([key,value]) => <div key={key} className="flex justify-between border-b border-slate-100 py-2"><span>{key.replaceAll("_"," ")}</span><strong>{value == null ? "Not measured" : value ? "PASS" : "MISS"}</strong></div>)}
            </div>
            <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{commercialScorecard.rationale.map((line)=><p key={line} className="mt-1 first:mt-0">{line}</p>)}</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="font-semibold">ROI model · pilot estimate</h2>
            <p className="mt-1 text-xs text-amber-700">{commercialScorecard.roi.note}</p>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <MiniMetric title="Minutes saved / claim" value={commercialScorecard.roi.minutes_saved_per_claim} />
              <MiniMetric title="Annual hours saved" value={commercialScorecard.roi.annual_hours_saved} />
              <MiniMetric title="Annual labor value" value={commercialScorecard.roi.annual_labor_value == null ? null : `${commercialScorecard.roi.currency} ${commercialScorecard.roi.annual_labor_value.toLocaleString()}`} />
              <MiniMetric title="Annual WTP midpoint" value={commercialScorecard.roi.annual_wtp_midpoint == null ? null : `${commercialScorecard.roi.currency} ${commercialScorecard.roi.annual_wtp_midpoint.toLocaleString()}`} />
              <MiniMetric title="ROI multiple" value={commercialScorecard.roi.estimated_roi_multiple == null ? null : `${commercialScorecard.roi.estimated_roi_multiple}×`} />
              <MiniMetric title="Payback" value={commercialScorecard.roi.estimated_payback_months == null ? null : `${commercialScorecard.roi.estimated_payback_months} months`} />
            </div>
          </div>
        </section>}

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
function MiniMetric({ title, value }: { title: string; value: string | number | null }) {
  return <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">{title}</p><p className="mt-1 font-semibold text-slate-900">{value == null ? "Not measured" : value}</p></div>;
}
function Field({ label, value, onChange, type="text" }: { label:string; value:string; onChange:(value:string)=>void; type?:string }) {
  return <label className="text-sm font-medium text-slate-700">{label}<input value={value} onChange={(e)=>onChange(e.target.value)} type={type} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>;
}
function SelectField({ label, value, onChange, options }: { label:string; value:string; onChange:(value:string)=>void; options:string[] }) {
  return <label className="text-sm font-medium text-slate-700">{label}<select value={value} onChange={(e)=>onChange(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2">{options.map((item)=><option key={item} value={item}>{item.replaceAll("_"," ")}</option>)}</select></label>;
}
function DecisionBadge({decision}:{decision:"GO"|"PIVOT"|"STOP"|"INSUFFICIENT_DATA"}) {
  const klass = decision === "GO" ? "bg-emerald-100 text-emerald-700" : decision === "STOP" ? "bg-red-100 text-red-700" : decision === "PIVOT" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-3 py-1 text-xs font-bold ${klass}`}>{decision.replaceAll("_"," ")}</span>;
}
