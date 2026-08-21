"use client";

import { useCallback, useEffect, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type Readiness = {
  id: string;
  assessment_key: string;
  status: string;
  outcome: string | null;
  rollout_percentage: number;
  summary: { broader_production_stage_recommended: boolean };
};

type Approval = { approval_role: string; action: string };
type Monitor = { status: string; metrics: Record<string, unknown> };
type Authorization = {
  id: string;
  authorization_key: string;
  status: string;
  previous_rollout_percentage: number;
  rollout_percentage: number;
  decision_hash: string | null;
  approvals: Approval[];
  monitors: Monitor[];
  summary: {
    broader_production_cohort_authorized: boolean;
    rollout_above_50_percent_authorized: boolean;
    production_wide_authorized: boolean;
    restricted_documents_authorized: boolean;
    new_document_classes_authorized: boolean;
    autonomous_claim_decisions_authorized: boolean;
    human_review_required: boolean;
  };
};

type ReadinessDashboard = { assessments: Readiness[] };
type BroaderDashboard = { authorizations: Authorization[] };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
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

const roles = ["security", "privacy", "product", "operations", "risk", "claims_governance"] as const;

export default function AIBroaderProductionPage() {
  const [readiness, setReadiness] = useState<ReadinessDashboard | null>(null);
  const [dashboard, setDashboard] = useState<BroaderDashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [readinessData, broaderData] = await Promise.all([
        request<ReadinessDashboard>("/ai-scale-up-outcomes"),
        request<BroaderDashboard>("/ai-broader-production"),
      ]);
      setReadiness(readinessData);
      setDashboard(broaderData);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11I controls.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const recommended = readiness?.assessments.find(
    (item) => item.status === "recommended" && item.outcome === "recommend_broader_production_stage",
  ) ?? null;
  const current = dashboard?.authorizations[0] ?? null;
  const approvedRoles = new Set(current?.approvals.filter((item) => item.action === "approve").map((item) => item.approval_role) ?? []);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try {
      await action();
      setMessage(success);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Sprint 11I action failed.");
    } finally {
      setBusy(null);
    }
  }

  async function create() {
    if (!recommended) return;
    const now = new Date();
    const expires = new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000);
    await act("create", () => request("/ai-broader-production/authorizations", {
      method: "POST",
      body: JSON.stringify({
        readiness_assessment_id: recommended.id,
        authorization_key: `broader-production-${crypto.randomUUID()}`,
        allowed_document_types: ["chief_engineer_report", "engine_log"],
        rollout_percentage: 50,
        max_claims: 20,
        max_documents: 60,
        max_users: 20,
        max_provider_runs: 200,
        starts_at: now.toISOString(),
        expires_at: expires.toISOString(),
        deployment_isolation_reference: "artifact://ai-broader-production/deployment-isolation",
        provider_project_reference: "artifact://ai-broader-production/provider-project",
        credential_control_reference: "artifact://ai-broader-production/credential-control",
        privacy_legal_reference: "artifact://ai-broader-production/privacy-legal",
        monitoring_reference: "monitor://ai-broader-production/live-controls",
        incident_response_reference: "runbook://ai-broader-production/incident-response",
        rollback_reference: "runbook://ai-broader-production/rollback-15-minutes",
        change_ticket_reference: "ticket://ai-broader-production/change",
        confirm_separate_broader_production: true,
      }),
    }), "Sprint 11I authorization attempt created; rollout is not active yet.");
  }

  async function approve(role: typeof roles[number]) {
    if (!current) return;
    await act(`approve-${role}`, () => request(
      `/ai-broader-production/authorizations/${current.id}/approvals`, {
        method: "POST",
        body: JSON.stringify({
          approval_role: role,
          action: "approve",
          evidence_reference: `artifact://ai-broader-production/${role}-approval`,
          note: `Independent ${role} reviewer reproduced the bounded Sprint 11I controls.`,
        }),
      }), `${role} approval recorded.`);
  }

  async function decide(outcome: "authorize_broader_production" | "hold" | "reject_progression") {
    if (!current) return;
    await act(`decision-${outcome}`, () => request(
      `/ai-broader-production/authorizations/${current.id}/decision`, {
        method: "POST",
        body: JSON.stringify({
          outcome,
          confirm_decision: true,
          note: outcome === "authorize_broader_production"
            ? "Authorize only this exact expiring 26–50% cohort; no Production-wide permission is granted."
            : "Do not activate broader-production progression until a new separately governed attempt is justified.",
        }),
      }), "Admin Sprint 11I decision recorded.");
  }

  async function monitor() {
    if (!current) return;
    await act("monitor", () => request(
      `/ai-broader-production/authorizations/${current.id}/monitors`, {
        method: "POST",
        body: JSON.stringify({
          monitor_key: `broader-monitor-${crypto.randomUUID()}`,
          note: "Freeze current human-review, grounding, quality, latency, cost and incident controls.",
          confirm_live_monitor_snapshot: true,
        }),
      }), "Live Sprint 11I monitor recorded.");
  }

  async function lifecycle(endpoint: "complete" | "revoke") {
    if (!current) return;
    await act(endpoint, () => request(
      `/ai-broader-production/authorizations/${current.id}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify({
          confirm: true,
          note: endpoint === "complete"
            ? "Complete only this bounded cohort after all different-human reviews and a fresh passing final monitor."
            : "Immediate Sprint 11I kill switch; no fallback to older Production control planes.",
        }),
      }), `Sprint 11I ${endpoint} action recorded.`);
  }

  const latestMonitor = current?.monitors.at(-1);

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11I · separately authorized broader-production cohort</p>
      <h1 className="mt-3 text-3xl font-semibold">Broader-production AI authorization</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Expand only from a positive 11H recommendation into an expiring deterministic 26–50% cohort. Six independent approvals, fresh document eligibility, different-human review, live monitoring, rollback and a kill switch remain mandatory.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Authorization", current?.status.replaceAll("_", " ") ?? "not created"],
        ["Rollout", current ? `${current.previous_rollout_percentage}% → ${current.rollout_percentage}%` : "26–50% envelope"],
        ["Latest monitor", latestMonitor?.status ?? "—"],
        ["Production-wide", "Not authorized"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize text-slate-900">{value}</p></div>)}
    </section>

    {!current && recommended && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Create the separately governed 11I attempt</h2>
      <p className="mt-2 text-sm text-slate-600">Anchor: {recommended.assessment_key}. Creation freezes its SHA-256 evidence and does not activate any rollout.</p>
      <button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create 50% bounded cohort attempt</button>
    </section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {current.authorization_key}</p><h2 className="mt-1 text-xl font-semibold">Six-party authorization chain</h2></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">{current.status.replaceAll("_", " ")}</span></div>
      <div className="mt-5 flex flex-wrap gap-2">
        {roles.map((role) => <button key={role} disabled={busy !== null || approvedRoles.has(role) || !["pending_approvals", "decision_ready"].includes(current.status)} onClick={() => void approve(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}
      </div>
      <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("authorize_broader_production")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Admin authorize bounded cohort</button>
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("hold")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Hold</button>
        <button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("reject_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Reject progression</button>
        <button disabled={busy !== null || !["authorized", "paused"].includes(current.status)} onClick={() => void monitor()} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-40">Record live monitor</button>
        <button disabled={busy !== null || current.status !== "authorized"} onClick={() => void lifecycle("complete")} className="rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-40">Complete cohort</button>
        <button disabled={busy !== null || ["revoked", "completed"].includes(current.status)} onClick={() => void lifecycle("revoke")} className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Kill switch</button>
      </div>
      {current.decision_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Authorization SHA-256: {current.decision_hash}</p>}
    </section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
      <strong>Hard boundary:</strong> Sprint 11I never authorizes rollout above 50%, Production-wide AI, Restricted documents, new document classes, autonomous liability/coverage/reserve/settlement/payment decisions, or automatic authoritative claim-fact updates. Every provider output still requires a different human reviewer.
    </section>
  </div>;
}
