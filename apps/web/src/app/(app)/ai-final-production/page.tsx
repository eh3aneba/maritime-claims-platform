"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";

type Readiness = { id: string; assessment_key: string; status: string; outcome: string | null };
type Approval = { approval_role: string; action: string };
type Authorization = {
  id: string; authorization_key: string; status: string; outcome: string | null;
  previous_rollout_percentage: number; rollout_percentage: number; approvals: Approval[];
  decision_hash: string | null; completion_hash: string | null;
  summary: {
    authorization_active: boolean; independent_approvals_complete: boolean;
    rollout_above_75_authorized: boolean; rollout_above_90_authorized: boolean;
    production_wide_authorized: boolean; restricted_documents_authorized: boolean;
    autonomous_claim_decisions_authorized: boolean; different_human_review_required: boolean;
  };
};
type ReadinessDashboard = { assessments: Readiness[] };
type Dashboard = { authorizations: Authorization[] };

const roles = ["security", "privacy", "product", "operations", "risk", "claims_governance", "ai_quality", "legal_data_governance", "business_owner"] as const;

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

export default function AIFinalProductionPage() {
  const [readiness, setReadiness] = useState<ReadinessDashboard | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<ReadinessDashboard>("/ai-final-production-readiness"),
        request<Dashboard>("/ai-final-production"),
      ]);
      setReadiness(a); setDashboard(b); setError(null);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11N."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const anchor = readiness?.assessments.find((item) => item.status === "recommended" && item.outcome === "recommend_separate_final_production_authorization") ?? null;
  const current = dashboard?.authorizations[0] ?? null;
  const approved = useMemo(() => new Set(current?.approvals.filter((item) => item.action === "approve").map((item) => item.approval_role) ?? []), [current]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11N action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!anchor) return;
    const start = new Date();
    const expiry = new Date(start.getTime() + 14 * 24 * 60 * 60 * 1000);
    await act("create", () => request("/ai-final-production/authorizations", {
      method: "POST",
      body: JSON.stringify({
        readiness_assessment_id: anchor.id,
        authorization_key: `final-production-${crypto.randomUUID()}`,
        allowed_document_types: ["chief_engineer_report", "engine_log"],
        rollout_percentage: 80,
        max_claims: 50, max_documents: 150, max_users: 50, max_provider_runs: 750,
        starts_at: start.toISOString(), expires_at: expiry.toISOString(),
        deployment_isolation_reference: "artifact://ai-final-production/deployment-isolation",
        provider_project_reference: "artifact://ai-final-production/provider-project",
        credential_control_reference: "artifact://ai-final-production/credential-control",
        privacy_legal_reference: "artifact://ai-final-production/privacy-legal",
        monitoring_reference: "runbook://ai-final-production/monitoring",
        incident_response_reference: "runbook://ai-final-production/incidents",
        rollback_reference: "runbook://ai-final-production/rollback",
        change_ticket_reference: "ticket://ai-final-production/authorization",
        confirm_separate_final_production: true,
      }),
    }), "Sprint 11N authorization attempt created; no rollout permission exists until nine approvals and a separate Admin decision.");
  }

  async function approve(role: typeof roles[number]) {
    if (!current) return;
    await act(`approve-${role}`, () => request(`/ai-final-production/authorizations/${current.id}/approvals`, {
      method: "POST",
      body: JSON.stringify({
        approval_role: role, action: "approve",
        evidence_reference: `artifact://ai-final-production/${role}-approval`,
        note: `Independent ${role} reviewer verified the immutable Sprint 11M anchor, bounded 76–90% envelope, kill switch and no-fallback controls.`,
      }),
    }), `${role} approval recorded.`);
  }

  async function decide(outcome: "authorize_final_production_cohort" | "hold_for_remediation" | "reject_progression") {
    if (!current) return;
    await act(`decision-${outcome}`, () => request(`/ai-final-production/authorizations/${current.id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        outcome, confirm_decision: true,
        note: outcome === "authorize_final_production_cohort"
          ? "Authorize only the bounded 76–90% Sprint 11N cohort. Production-wide, >90%, Restricted documents and autonomous claim decisions remain prohibited."
          : "Do not activate the Sprint 11N cohort until the bounded authorization controls are satisfied.",
      }),
    }), "Sprint 11N Admin decision recorded.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11N · Final Production AI Cohort</p>
      <h1 className="mt-3 text-3xl font-semibold">Bounded 76–90% Production authorization</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">A separately authorized, expiring control plane anchored to one positive Sprint 11M decision. Nine independent reviewers plus a separate Admin are required. Fresh document eligibility, different-human review, no-fallback runtime precedence and live rollback monitoring remain mandatory.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Authorization", current?.status.replaceAll("_", " ") ?? "not created"], ["Rollout", current ? `${current.rollout_percentage}%` : "76–90% only"], ["Approvals", current ? `${approved.size}/9` : "0/9"], ["Production-wide", "Not authorized"]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {!current && anchor && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Create a separate 11N attempt</h2><p className="mt-2 text-sm text-slate-600">Positive Sprint 11M anchor: {anchor.assessment_key}. The default UI request is an 80% cohort with bounded claim/document/user/provider-run caps and 14-day expiry.</p><button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create Sprint 11N authorization</button></section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Nine independent authorization reviews</h2><p className="mt-2 text-sm text-slate-600">Requester and final Admin cannot occupy any reviewer role. Every approval requires bounded evidence.</p><div className="mt-4 flex flex-wrap gap-2">{roles.map((role) => <button key={role} disabled={busy !== null || approved.has(role) || !["pending_approvals", "decision_ready"].includes(current.status)} onClick={() => void approve(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}</div><div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5"><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("authorize_final_production_cohort")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Authorize bounded 76–90% cohort</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("hold_for_remediation")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Hold for remediation</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("reject_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Reject progression</button></div>{current.decision_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}{current.completion_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Completion SHA-256: {current.completion_hash}</p>}</section>}

    {current && <section className="grid gap-3 md:grid-cols-3"><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Newest control plane</p><p className="mt-2 text-sm">11N precedence is active once an attempt exists. Inactive 11N never falls back to 11K.</p></div><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Human authority</p><p className="mt-2 text-sm">Different-human output review remains mandatory; liability, coverage, reserve, settlement and payment decisions remain human.</p></div><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Next boundary</p><p className="mt-2 text-sm">Completion grants no permission above 90%. A separate measured outcome gate is required before any 91–100% discussion.</p></div></section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Hard boundary:</strong> Sprint 11N never authorizes rollout above 90%, Production-wide AI, Restricted documents, new document classes, autonomous liability/coverage/reserve/settlement/payment/recovery decisions, automatic authoritative claim facts, or removal of different-human review.</section>
  </div>;
}
