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
    bounded_100_percent_cohort_authorized: boolean; rollout_100_percent_authorized: boolean;
    production_wide_unbounded_authorized: boolean; restricted_documents_authorized: boolean;
    new_document_classes_authorized: boolean; autonomous_claim_decisions_authorized: boolean;
    different_human_review_required: boolean;
  };
};
type OutcomeDashboard = { assessments: Outcome[] };
type Dashboard = { authorizations: Authorization[] };

const roles = [
  "security", "privacy", "product", "operations", "risk", "claims_governance",
  "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
  "independent_production_assurance", "data_protection", "executive_production_sponsor",
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

export default function AIBoundedFullProductionPage() {
  const [outcomes, setOutcomes] = useState<OutcomeDashboard | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<OutcomeDashboard>("/ai-near-universal-outcomes"),
        request<Dashboard>("/ai-bounded-full-production"),
      ]);
      setOutcomes(a); setDashboard(b); setError(null);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11R."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const anchor = outcomes?.assessments.find((item) => item.status === "recommended" && item.outcome === "recommend_separate_100_percent_authorization_review") ?? null;
  const current = dashboard?.authorizations[0] ?? null;
  const approved = useMemo(() => new Set(current?.approvals.filter((item) => item.action === "approve").map((item) => item.approval_role) ?? []), [current]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11R action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!anchor) return;
    const start = new Date();
    const expiry = new Date(start.getTime() + 20 * 24 * 60 * 60 * 1000);
    await act("create", () => request("/ai-bounded-full-production/authorizations", {
      method: "POST",
      body: JSON.stringify({
        near_universal_outcome_assessment_id: anchor.id,
        authorization_key: `bounded-full-${crypto.randomUUID()}`,
        allowed_document_types: ["chief_engineer_report", "engine_log"],
        rollout_percentage: 100,
        max_claims: 110, max_documents: 330, max_users: 110, max_provider_runs: 1900,
        starts_at: start.toISOString(), expires_at: expiry.toISOString(),
        deployment_isolation_reference: "artifact://ai-bounded-full/deployment-isolation",
        provider_project_reference: "artifact://ai-bounded-full/provider-project",
        credential_control_reference: "artifact://ai-bounded-full/credential-control",
        privacy_legal_reference: "artifact://ai-bounded-full/privacy-legal",
        monitoring_reference: "monitor://ai-bounded-full/live-controls",
        incident_response_reference: "runbook://ai-bounded-full/incidents",
        rollback_reference: "runbook://ai-bounded-full/rollback",
        platform_reliability_reference: "artifact://ai-bounded-full/platform-reliability",
        data_protection_reference: "artifact://ai-bounded-full/data-protection",
        executive_sponsor_reference: "artifact://ai-bounded-full/executive-sponsor",
        change_ticket_reference: "ticket://ai-bounded-full/authorization",
        confirm_separate_bounded_full_production: true,
      }),
    }), "Sprint 11R attempt created. No bounded 100% authorization exists until thirteen independent approvals and a separate Admin decision.");
  }

  async function approve(role: typeof roles[number]) {
    if (!current) return;
    await act(`approve-${role}`, () => request(`/ai-bounded-full-production/authorizations/${current.id}/approvals`, {
      method: "POST",
      body: JSON.stringify({ approval_role: role, action: "approve",
        evidence_reference: `artifact://ai-bounded-full/${role}-approval`,
        note: `Independent ${role} reviewer verified the immutable Sprint 11Q anchor, bounded 100% envelope, human-review, rollback and no-fallback controls.` }),
    }), `${role} approval recorded.`);
  }

  async function decide(outcome: "authorize_bounded_100_percent_cohort" | "hold_for_remediation" | "reject_progression") {
    if (!current) return;
    await act(`decision-${outcome}`, () => request(`/ai-bounded-full-production/authorizations/${current.id}/decision`, {
      method: "POST",
      body: JSON.stringify({ outcome, confirm_decision: true,
        note: outcome === "authorize_bounded_100_percent_cohort"
          ? "Authorize only this bounded 100% Sprint 11R cohort. Unbounded Production-wide AI, Restricted documents and autonomous claim decisions remain prohibited."
          : "Do not activate Sprint 11R until every bounded authorization control is satisfied." }),
    }), "Sprint 11R Admin decision recorded.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11R · Bounded 100% Production AI</p>
      <h1 className="mt-3 text-3xl font-semibold">100% coverage inside one explicit bounded cohort</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">This is not blanket Production-wide authorization. It remains tenant-scoped, time-limited, capped, limited to Chief Engineer Reports and Engine Logs, and requires different-human review for every provider output.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Authorization", current?.status.replaceAll("_", " ") ?? "not created"], ["Bounded rollout", current ? `${current.rollout_percentage}%` : "100% only"], ["Approvals", current ? `${approved.size}/13` : "0/13"], ["Unbounded Production-wide", "Not authorized"]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {!current && anchor && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Create separate Sprint 11R attempt</h2><p className="mt-2 text-sm text-slate-600">Positive Sprint 11Q anchor: {anchor.assessment_key}. Default UI request remains capped and expires after 20 days.</p><button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create bounded 100% authorization</button></section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Thirteen independent authorization reviews</h2><p className="mt-2 text-sm text-slate-600">Requester and final Admin cannot occupy a reviewer role. Data Protection and Executive Production Sponsor are explicit final-stage controls.</p><div className="mt-4 flex flex-wrap gap-2">{roles.map((role) => <button key={role} disabled={busy !== null || approved.has(role) || !["pending_approvals", "decision_ready"].includes(current.status)} onClick={() => void approve(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}</div><div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5"><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("authorize_bounded_100_percent_cohort")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Authorize bounded 100% cohort</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("hold_for_remediation")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Hold for remediation</button><button disabled={busy !== null || current.status !== "decision_ready"} onClick={() => void decide("reject_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Reject progression</button></div>{current.decision_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}{current.completion_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Completion SHA-256: {current.completion_hash}</p>}</section>}

    <section className="grid gap-3 md:grid-cols-3"><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Newest control plane</p><p className="mt-2 text-sm">As soon as an 11R attempt exists, inactive 11R cannot fall back to 11P or any earlier Production stage.</p></div><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Human authority</p><p className="mt-2 text-sm">Every provider output remains different-human reviewed. Coverage, liability, causation, reserve, settlement, payment and recovery decisions remain human-owned.</p></div><div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs font-semibold uppercase text-slate-500">Next boundary</p><p className="mt-2 text-sm">Completion does not authorize unbounded Production-wide use. A measured 100% outcome and enterprise-readiness gate must come next.</p></div></section>

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Hard boundary:</strong> 100% here means only every eligible item inside this explicit bounded cohort. It never authorizes Restricted documents, new document classes, autonomous claim decisions, automatic authoritative facts, removal of different-human review, or unbounded Production-wide AI.</section>
  </div>;
}
