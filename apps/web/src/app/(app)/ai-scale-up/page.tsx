"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  attestScaleUpDocument, completeScaleUp, createScaleUp, decideScaleUp,
  getGraduationRecommendations, getScaleUpDashboard, monitorScaleUp,
  reportScaleUpIncident, resolveScaleUpIncident, resumeScaleUp, reviewScaleUp,
  reviewScaleUpRun, revokeScaleUp, type GraduationAssessment,
  type ScaleUpApprovalRole, type ScaleUpAuthorization,
} from "@/lib/ai-scale-up-api";

const controlClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

function Badge({ value }: { value: string }) {
  const good = ["authorized", "decision_ready", "pass", "completed"].includes(value);
  const bad = ["rejected", "revoked", "rollback_required"].includes(value);
  const klass = good ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : bad ? "bg-rose-50 text-rose-700 ring-rose-200"
      : "bg-amber-50 text-amber-700 ring-amber-200";
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${klass}`}>{value.replaceAll("_", " ")}</span>;
}

function numberMetric(item: ScaleUpAuthorization | null, key: string) {
  const value = item?.monitors.at(-1)?.metrics?.[key];
  return typeof value === "number" ? value : null;
}

function percentBps(value: number | null) {
  return value === null ? "—" : `${(value / 100).toFixed(2)}%`;
}

export default function AIScaleUpPage() {
  const [items, setItems] = useState<ScaleUpAuthorization[]>([]);
  const [recommendations, setRecommendations] = useState<GraduationAssessment[]>([]);
  const [claimId, setClaimId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [dashboard, graduation] = await Promise.all([
        getScaleUpDashboard(), getGraduationRecommendations(),
      ]);
      setItems(dashboard.authorizations); setRecommendations(graduation); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load the controlled scale-up gate.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  const current = items[0] ?? null;
  const positiveRecommendation = recommendations[0] ?? null;
  const reviewedRoles = useMemo(
    () => new Set(current?.approvals.map((entry) => entry.approval_role) ?? []), [current]);

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "The Sprint 11G action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!positiveRecommendation) {
      setError("A positive Sprint 11F graduation recommendation is required."); return;
    }
    await run("create", () => createScaleUp(positiveRecommendation.id),
      "A separate 11–25% controlled scale-up authorization attempt was created.");
  }

  async function attest(event: FormEvent) {
    event.preventDefault();
    if (!current || !claimId || !documentId) return;
    await run("attest", () => attestScaleUpDocument(current.id, claimId.trim(), documentId.trim()),
      "Fresh Sprint 11G document eligibility recorded; earlier eligibility was not carried forward.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11G · controlled scale-up</p>
      <h1 className="mt-3 text-3xl font-semibold">Controlled AI scale-up authorization</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">
        Increase the measured CE Report / Engine Log cohort only through a separately approved 11–25% Production authorization. Five independent reviewers, fresh document eligibility, different-human review, grounding/quality monitoring, expiry and rollback remain mandatory.
      </p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Authorization", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Declared rollout", current ? `${current.rollout_percentage}%` : "—"],
        ["Reviewed runs", current ? `${current.summary.human_reviewed_run_count}/${current.summary.provider_run_count}` : "0/0"],
        ["Production-wide", "No"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize text-slate-900">{value}</p></div>)}
    </section>

    {!current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Start a separate controlled scale-up attempt</h2>
      <p className="mt-2 text-sm text-slate-600">
        {positiveRecommendation
          ? `Positive 11F assessment ${positiveRecommendation.id} is available. Its recorded rollout was ${positiveRecommendation.rollout_percentage}%.`
          : "No positive 11F graduation recommendation is available."}
      </p>
      <button disabled={busy !== null || !positiveRecommendation} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create 25% authorization attempt</button>
    </section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {current.attempt_number} · {current.authorization_mode}</p><h2 className="mt-1 text-xl font-semibold">{current.authorization_key}</h2><p className="mt-1 text-xs text-slate-500">11F assessment {current.outcome_assessment_id}</p></div>
        <Badge value={current.status} />
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["Prior rollout", `${current.previous_rollout_percentage}%`],
          ["New rollout", `${current.rollout_percentage}%`],
          ["Reject rate", percentBps(numberMetric(current, "human_reject_rate_bps"))],
          ["Unsupported", percentBps(numberMetric(current, "unsupported_output_rate_bps"))],
          ["Grounding", percentBps(numberMetric(current, "source_grounding_validity_bps"))],
          ["P95 latency", `${numberMetric(current, "p95_latency_ms") ?? "—"}ms`],
        ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}
      </div>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
        {(["security", "privacy", "product", "operations", "risk"] as ScaleUpApprovalRole[]).map((role) => <button key={role} disabled={busy !== null || reviewedRoles.has(role) || !["pending_approvals", "decision_ready"].includes(current.status)} onClick={() => void run(`review-${role}`, () => reviewScaleUp(current.id, role, "approve"), `${role} approval recorded.`)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role} approve</button>)}
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void run("authorize", () => decideScaleUp(current.id, "authorize_scale_up"), "Controlled scale-up authorized; Production-wide use remains blocked.")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Authorize bounded scale-up</button>
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void run("hold", () => decideScaleUp(current.id, "hold"), "Scale-up held; no wider authorization granted.")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Hold</button>
      </div>
      <p className="mt-3 text-xs text-slate-500">Requester plus Security, Privacy, Product, Operations and Risk approvers must be separate where required; only Admin records the final authorization decision.</p>
    </section>}

    {current?.status === "authorized" && <section className="grid gap-5 lg:grid-cols-2">
      <form onSubmit={attest} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">Fresh document eligibility</h2>
        <p className="mt-2 text-sm text-slate-600">11E eligibility never carries forward. Enter a current Claim ID and CE Report / Engine Log Document ID that falls inside the deterministic 25% bucket.</p>
        <div className="mt-4 space-y-3"><input required value={claimId} onChange={(event) => setClaimId(event.target.value)} placeholder="Claim UUID" className={controlClass} /><input required value={documentId} onChange={(event) => setDocumentId(event.target.value)} placeholder="Document UUID" className={controlClass} /></div>
        <button disabled={busy !== null} className="mt-4 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Attest fresh eligibility</button>
      </form>
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">Live controls</h2>
        <p className="mt-2 text-sm text-slate-600">Monitor failures and incidents pause execution; resume never expands the authorized percentage.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button disabled={busy !== null} onClick={() => void run("monitor", () => monitorScaleUp(current.id), "Live content-free scale-up monitor recorded.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record live monitor</button>
          <button disabled={busy !== null} onClick={() => void run("incident", () => reportScaleUpIncident(current.id), "Incident recorded; controlled scale-up paused and rollback required.")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Report incident</button>
          <button disabled={busy !== null} onClick={() => void run("complete", () => completeScaleUp(current.id), "Controlled cohort completed; no Production-wide authorization created.")} className="rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-40">Complete cohort</button>
          <button disabled={busy !== null} onClick={() => void run("revoke", () => revokeScaleUp(current.id), "Sprint 11G kill switch activated.")} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-40">Kill switch</button>
        </div>
      </div>
    </section>}

    {current?.status === "paused" && <section className="rounded-2xl border border-amber-200 bg-amber-50 p-6">
      <h2 className="text-lg font-semibold text-amber-950">Paused — rollback remains in force</h2>
      <div className="mt-4 flex flex-wrap gap-2">
        {current.incidents.filter((entry) => entry.status === "open").map((entry) => <button key={entry.id} disabled={busy !== null} onClick={() => void run(`resolve-${entry.id}`, () => resolveScaleUpIncident(current.id, entry.id), "Incident resolved; fresh monitoring is still required.")} className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-amber-900 ring-1 ring-amber-300 disabled:opacity-40">Resolve {entry.category} incident</button>)}
        <button disabled={busy !== null} onClick={() => void run("monitor-paused", () => monitorScaleUp(current.id), "Recovery monitor recorded.")} className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-amber-900 ring-1 ring-amber-300 disabled:opacity-40">Record recovery monitor</button>
        <button disabled={busy !== null} onClick={() => void run("resume", () => resumeScaleUp(current.id), "Admin resumed the same bounded rollout after recovery controls passed.")} className="rounded-lg bg-amber-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Resume same rollout</button>
      </div>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Content-free run ledger</h2>
      <div className="mt-4 space-y-2">{current?.runs.length ? current.runs.map((runItem) => <div key={runItem.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{runItem.task_type.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-500">run {runItem.id} · {runItem.status.replaceAll("_", " ")}</p></div><div className="flex gap-2">{runItem.status === "queued" && (["approve", "edit", "reject"] as const).map((action) => <button key={action} disabled={busy !== null} onClick={() => void run(`run-${runItem.id}-${action}`, () => reviewScaleUpRun(runItem.id, action), `Different-human ${action} review recorded.`)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold capitalize disabled:opacity-40">{action}</button>)}<Badge value={runItem.status} /></div></div>) : <p className="text-sm text-slate-500">No Sprint 11G provider runs recorded.</p>}</div>
    </section>

    <section className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm leading-6 text-rose-900"><strong>Hard boundary:</strong> Sprint 11G can authorize only the declared 11–25% CE Report / Engine Log cohort. It cannot authorize Production-wide traffic, rollout above 25%, Restricted documents, new document classes, autonomous claim decisions or automatic authoritative-fact updates.</section>
  </div>;
}
