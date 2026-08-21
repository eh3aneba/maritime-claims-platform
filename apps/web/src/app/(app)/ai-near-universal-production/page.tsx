"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";

type Outcome = { id: string; assessment_key: string; status: string; outcome: string | null };
type Approval = { approval_role: string; action: string };
type Authorization = {
  id: string; authorization_key: string; status: string; outcome: string | null;
  previous_rollout_percentage: number; rollout_percentage: number; approvals: Approval[];
  decision_hash: string | null; completion_hash: string | null;
  summary: {
    authorization_active: boolean; independent_approvals_complete: boolean;
    rollout_above_90_authorized: boolean; rollout_100_percent_authorized: boolean;
    production_wide_authorized: boolean; restricted_documents_authorized: boolean;
    autonomous_claim_decisions_authorized: boolean; different_human_review_required: boolean;
  };
};
type OutcomeDashboard = { assessments: Outcome[] };
type Dashboard = { authorizations: Authorization[] };

const roles = [
  "security", "privacy", "product", "quality", "operations", "risk",
  "claims_governance", "ai_quality", "legal_data_governance", "business_owner",
  "platform_reliability",
] as const;

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

export default function AINearUniversalProductionPage() {
  const [outcomes, setOutcomes] = useState<OutcomeDashboard | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<OutcomeDashboard>("/ai-final-production-outcomes"),
        request<Dashboard>("/ai-near-universal-production"),
      ]);
      setOutcomes(a); setDashboard(b); setError(null);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11P."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const anchor = outcomes?.assessments.find((item) => item.status === "recommended" && item.outcome === "recommend_separate_91_100_authorization_review") ?? null;
  const current = dashboard?.authorizations[0] ?? null;
  const approved = useMemo(() => new Set(current?.approvals.filter((item) => item.action === "approve").map((item) => item.approval_role) ?? []), [current]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11P action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!anchor) return;
    const start = new Date();
    const expiry = new Date(start.getTime() + 14 * 24 * 60 * 60 * 1000);
    await act("create", () => request("/ai-near-universal-production/authorizations", {
      method: "POST",
      body: JSON.stringify({
        outcome_assessment_id: anchor.id,
        authorization_key: `near-universal-${crypto.randomUUID()}`,
        allowed_document_types: ["chief_engineer_report", "engine_log"],
        rollout_percentage: 95,
        max_claims: 75, max_documents: 225, max_users: 75, max_provider_runs: 1200,
        starts_at: start.toISOString(), expires_at: expiry.toISOString(),
        deployment_isolation_reference: "artifact://ai-near-universal/deployment-isolation",
        provider_project_reference: "artifact://ai-near-universal/provider-project",
        credential_control_reference: "artifact://ai-near-universal/credential-control",
        privacy_legal_reference: "artifact://ai-near-universal/privacy-legal",
        monitoring_reference: "monitor://ai-near-universal/live-controls",
        incident_response_reference: "runbook://ai-near-universal/incidents",
        rollback_reference: "runbook://ai-near-universal/rollback",
        platform_reliability_reference: "artifact://ai-near-universal/platform-reliability",
        change_ticket_reference: "ticket://ai-near-universal/authorization",
        confirm_separate_near_universal: true,
      }),
    }), "Sprint 11P attempt created; no 91–99% rollout exists until eleven approvals and a separate Admin decision.");
  }

  async function approve(role: typeof roles[number]) {
    if (!current) return;
    await act(`approve-${role}`, () => request(`/ai-near-universal-production/authorizations/${current.id}/approvals`, {
      method: "POST",
      body: JSON.stringify({
        approval_role: role, action: "approve",
        evidence_reference: `artifact://ai-near-universal/${role}-approval`,
        note: `Independent ${role} reviewer verified the immutable Sprint 11O anchor, bounded 91–99% envelope, kill switch and no-fallback controls.`,
      }),
    }), `${role} approval recorded.`);
  }

  async function decide(outcome: "authorize_near_universal_91_99_cohort" | "hold_for_remediation" | "reject_progression") {
    if (!current) return;
    await act(`decision-${outcome}`, () => request(`/ai-near-universal-production/authorizations/${current.id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        outcome, confirm_decision: true,
        note: outcome === "authorize_near_universal_91_99_cohort"
          ? "Authorize only the bounded 91–99% Sprint 11P cohort. 100%, Production-wide, Restricted documents and autonomous claim decisions remain prohibited."
          : "Do not activate Sprint 11P until all bounded authorization controls are satisfied.",
      }),
    }), "Sprint 11P Admin decision recorded.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11P · Near-Universal Production AI</p>
      <h1 className="mt-3 text-3xl font-semibold">Bounded 91–99% Production authorization</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">A separately authorized, expiring control plane anchored to one positive Sprint 11O recommendation. Eleven independent reviewers plus a separate Admin are required. Fresh eligibility, different-human review, live rollback monitoring and strict no-fallback precedence remain mandatory.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Authorization", current?.status.replaceAll("_", " ") ?? "not created"], ["Rollout", current ? `${current.rollout_percentage}%` : "91–99% only"], ["Approvals", current ? `${approved.size}/11` : "0/11"], ["100% / Production-wide", "Not authorized"]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {!current && anchor && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Create a separate 11P attempt</h2><p className="mt-2 text-sm text-slate-600">Positive Sprint 11O anchor: {anchor.assessment_key}. Default UI request: 95% cohort, bounded caps and 14-day expiry.</p><button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create Sprint 11P authorization</button></section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Eleven independent authorization reviews</h2><p className="mt-2 text-sm text-slate-600">Requester and final Admin cannot occupy any reviewer role. Platform Reliability / SRE is an explicit eleventh reviewer.</p><div className="mt-4 flex flex-wrap gap-2">{roles.map((role) => <button key={role} disabled={busy !== null || approved.has(role) || !["pending_approvals", "decision_ready"].includes(current.status)} onClick={() => void approve(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}</div><div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5"><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("authorize_near_universal_91_99_cohort")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Authorize bounded 91–99% cohort</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("hold_for_remediation")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Hold for remediation</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("reject_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Reject progression</button></div>{current.decision_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}{current.completion_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Completion SHA-256: {current.completion_hash}</p>}</section>}

    {current && <section className="grid gap-3 md:grid-cols-3"><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Newest control plane</p><p className="mt-2 text-sm">11P precedence begins as soon as an attempt exists. Inactive 11P never falls back to 11N.</p></div><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Human authority</p><p className="mt-2 text-sm">Different-human output review remains mandatory; liability, coverage, reserve, settlement, payment and recovery decisions remain human.</p></div><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Next boundary</p><p className="mt-2 text-sm">Completion grants no 100% permission. Sprint 11Q must measure the 91–99% cohort before 100% can even be recommended.</p></div></section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Hard boundary:</strong> Sprint 11P never authorizes 100% rollout, Production-wide AI, Restricted documents, new document classes, autonomous liability/coverage/reserve/settlement/payment/recovery decisions, automatic authoritative claim facts, or removal of different-human review.</section>
  </div>;
}
