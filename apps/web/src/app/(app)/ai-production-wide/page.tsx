"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";

type Assessment = { id: string; status: string; outcome: string | null; decision_hash: string | null };
type AssessmentDashboard = { assessments: Assessment[] };
type Approval = { approval_role: string; action: string };
type Authorization = {
  id: string; authorization_key: string; status: string; outcome: string | null;
  starts_at: string; expires_at: string; policy_hash: string; decision_hash: string | null;
  approvals: Approval[]; eligibility_decisions: unknown[]; decision_logs: unknown[]; incidents: unknown[];
  summary: Record<string, boolean | number>;
};
type Dashboard = { authorizations: Authorization[] };

const roles = [
  "security", "privacy", "product", "operations", "risk", "claims_governance",
  "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
  "independent_production_assurance", "data_protection", "executive_production_sponsor",
  "enterprise_architecture_resilience", "internal_audit_model_risk",
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

export default function AIProductionWidePage() {
  const [outcomes, setOutcomes] = useState<AssessmentDashboard | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<AssessmentDashboard>("/ai-bounded-full-production-outcomes"),
        request<Dashboard>("/ai-production-wide"),
      ]);
      setOutcomes(a); setDashboard(b); setError(null);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11T."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const anchor = outcomes?.assessments.find((item) => item.status === "recommended" && item.outcome === "recommend_separate_production_wide_authorization_review" && item.decision_hash) ?? null;
  const current = dashboard?.authorizations[0] ?? null;
  const approved = useMemo(() => new Set(current?.approvals.filter((x) => x.action === "approve").map((x) => x.approval_role) ?? []), [current]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11T action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!anchor) return;
    const now = new Date(); const expires = new Date(now.getTime() + 89 * 86400000);
    await act("create", () => request("/ai-production-wide/authorizations", {
      method: "POST", body: JSON.stringify({
        bounded_full_outcome_assessment_id: anchor.id,
        authorization_key: `production-wide-${crypto.randomUUID()}`,
        allowed_document_types: ["chief_engineer_report", "engine_log"],
        starts_at: now.toISOString(), expires_at: expires.toISOString(),
        eligibility_policy_version: "production-eligibility-v1",
        eligibility_policy_reference: "policy://ai-production-wide/eligibility-v1",
        legal_basis_policy_reference: "policy://ai-production-wide/legal-basis-v1",
        data_minimization_policy_reference: "policy://ai-production-wide/data-minimization-v1",
        deployment_isolation_reference: "artifact://ai-production-wide/deployment-isolation",
        provider_project_reference: "artifact://ai-production-wide/provider-project",
        credential_control_reference: "artifact://ai-production-wide/credential-control",
        monitoring_reference: "monitor://ai-production-wide/live-controls",
        incident_response_reference: "runbook://ai-production-wide/incidents",
        rollback_reference: "runbook://ai-production-wide/rollback",
        model_change_control_reference: "policy://ai-production-wide/model-change",
        internal_audit_reference: "artifact://ai-production-wide/internal-audit",
        change_ticket_reference: "ticket://ai-production-wide/authorization",
        confirm_production_wide_human_reviewed_ai: true,
      }),
    }), "Sprint 11T Production-wide authorization review created.");
  }

  async function approve(role: typeof roles[number]) {
    if (!current) return;
    await act(`approve-${role}`, () => request(`/ai-production-wide/authorizations/${current.id}/approvals`, {
      method: "POST", body: JSON.stringify({
        approval_role: role, action: "approve", evidence_reference: `artifact://ai-production-wide/${role}-approval`,
        note: `Independent ${role} reviewer verified the Production-wide human-reviewed control envelope.`,
      }),
    }), `${role} approval recorded.`);
  }

  async function decide(outcome: "authorize_production_wide_human_reviewed_ai" | "hold_for_production_remediation" | "reject_production_wide_authorization") {
    if (!current) return;
    await act(`decide-${outcome}`, () => request(`/ai-production-wide/authorizations/${current.id}/decision`, {
      method: "POST", body: JSON.stringify({ outcome, confirm_decision: true,
        note: "Record the final Sprint 11T decision for the exact CE Report / Engine Log human-reviewed Production-wide scope." }),
    }), "Sprint 11T Admin decision recorded.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11T · Final Production AI Authorization</p>
      <h1 className="mt-3 text-3xl font-semibold">Production-wide Human-reviewed AI</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Final authorization layer for the already-proven Chief Engineer Report and Engine Log workflows. Production-wide removes percentage cohorts, not human review, confidentiality controls, tenant boundaries or model-change governance.</p>
    </section>

    {(message || error) && <div className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Authorization", current?.status.replaceAll("_", " ") ?? "not created"], ["Independent approvals", `${approved.size}/15`], ["Eligibility", "Policy-driven"], ["Human review", "Mandatory"]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {!current && anchor && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Create Production-wide authorization review</h2><p className="mt-2 text-sm text-slate-600">The positive Sprint 11S recommendation is available. This creates a maximum 90-day authorization review; it does not activate AI until all fifteen approvals and a separate Admin decision are recorded.</p><button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create Sprint 11T</button></section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Fifteen independent approvals</h2><p className="mt-2 text-sm text-slate-600">Internal Audit / Model Risk Assurance is the fifteenth independent review. The final Admin must be a sixteenth distinct person.</p><div className="mt-4 flex flex-wrap gap-2">{roles.map((role) => <button key={role} disabled={busy !== null || approved.has(role) || current.status !== "pending_approvals"} onClick={() => void approve(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")}</button>)}</div>{current.status === "decision_ready" && <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5"><button disabled={busy !== null} onClick={() => void decide("authorize_production_wide_human_reviewed_ai")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white">Authorize human-reviewed Production-wide AI</button><button disabled={busy !== null} onClick={() => void decide("hold_for_production_remediation")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800">Hold for remediation</button><button disabled={busy !== null} onClick={() => void decide("reject_production_wide_authorization")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700">Reject</button></div>}</section>}

    {current && <section className="grid gap-4 md:grid-cols-3"><div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold uppercase text-slate-500">Eligibility decisions</p><p className="mt-2 text-2xl font-semibold">{current.eligibility_decisions.length}</p></div><div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold uppercase text-slate-500">AI Decision Log entries</p><p className="mt-2 text-2xl font-semibold">{current.decision_logs.length}</p></div><div className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold uppercase text-slate-500">Incidents</p><p className="mt-2 text-2xl font-semibold">{current.incidents.length}</p></div></section>}

    {current && <section className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-xs font-semibold uppercase text-slate-500">Production Eligibility Policy SHA-256</p><p className="mt-2 break-all font-mono text-xs text-slate-600">{current.policy_hash}</p>{current.decision_hash && <><p className="mt-4 text-xs font-semibold uppercase text-slate-500">Authorization decision SHA-256</p><p className="mt-2 break-all font-mono text-xs text-slate-600">{current.decision_hash}</p></>}</section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Permanent boundary:</strong> Production-wide means all eligible CE Report and Engine Log workload inside the authorized tenant—not unrestricted AI. Restricted documents, new document classes, autonomous claim decisions and automatic authoritative facts remain prohibited; different-human review stays mandatory.</section>
  </div>;
}
