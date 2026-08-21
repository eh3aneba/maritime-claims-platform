"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, ApiError } from "@/lib/api";

type Authorization = { id: string; authorization_key: string; status: string; outcome: string | null; rollout_percentage: number; completion_hash: string | null };
type AuthorizationDashboard = { authorizations: Authorization[] };
type Review = { review_role: string; action: string };
type EnterpriseEvidence = { control_category: string; passed: boolean };
type Assessment = {
  id: string; assessment_key: string; status: string; outcome: string | null;
  rollout_percentage: number; assessment_hash: string | null; decision_hash: string | null;
  metrics: Record<string, unknown> | null; failure_reasons: string[]; reviews: Review[];
  enterprise_evidence: EnterpriseEvidence[];
  summary: { production_wide_unbounded_authorized: boolean; different_human_review_required: boolean; recommendation_only: boolean };
};
type OutcomeDashboard = { assessments: Assessment[] };

const roles = [
  "security", "privacy", "product", "operations", "risk", "claims_governance",
  "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
  "independent_production_assurance", "data_protection", "executive_production_sponsor",
  "enterprise_architecture_resilience",
] as const;

const enterpriseControls = [
  "kill_switch_rollback", "monitor_alerting", "audit_hash_traceability", "tenant_isolation",
  "privacy_data_protection", "availability_recovery", "change_control_integrity",
  "unit_economics", "human_escalation_ownership", "incident_executive_ownership",
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

export default function AIBoundedFullProductionOutcomesPage() {
  const [authorizations, setAuthorizations] = useState<AuthorizationDashboard | null>(null);
  const [dashboard, setDashboard] = useState<OutcomeDashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        request<AuthorizationDashboard>("/ai-bounded-full-production"),
        request<OutcomeDashboard>("/ai-bounded-full-production-outcomes"),
      ]);
      setAuthorizations(a); setDashboard(b); setError(null);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load Sprint 11S."); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const anchor = authorizations?.authorizations.find((item) => item.status === "completed" && item.outcome === "authorize_bounded_100_percent_cohort" && item.completion_hash) ?? null;
  const current = dashboard?.assessments[0] ?? null;
  const approved = useMemo(() => new Set(current?.reviews.filter((item) => item.action === "approve").map((item) => item.review_role) ?? []), [current]);
  const enterprise = useMemo(() => new Map(current?.enterprise_evidence.map((item) => [item.control_category, item.passed]) ?? []), [current]);

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setError(null); setMessage(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "Sprint 11S action failed."); }
    finally { setBusy(null); }
  }

  async function create() {
    if (!anchor) return;
    await act("create", () => request("/ai-bounded-full-production-outcomes/assessments", {
      method: "POST",
      body: JSON.stringify({
        bounded_full_authorization_id: anchor.id,
        assessment_key: `bounded-full-outcome-${crypto.randomUUID()}`,
        confirm_content_free_assessment: true,
      }),
    }), "Sprint 11S assessment created. Production-wide remains unauthorized while evidence is collected.");
  }

  async function finalize() {
    if (!current) return;
    await act("finalize", () => request(`/ai-bounded-full-production-outcomes/assessments/${current.id}/finalize`, {
      method: "POST",
      body: JSON.stringify({ confirm_finalize: true, note: "Freeze the 100% bounded cohort scorecard, business evidence, enterprise controls, monitor history, incidents and recovery evidence." }),
    }), "Sprint 11S scorecard finalized for independent review.");
  }

  async function approve(role: typeof roles[number]) {
    if (!current) return;
    await act(`approve-${role}`, () => request(`/ai-bounded-full-production-outcomes/assessments/${current.id}/reviews`, {
      method: "POST",
      body: JSON.stringify({
        review_role: role, action: "approve",
        evidence_reference: `artifact://ai-bounded-full-outcomes/${role}-review`,
        note: `Independent ${role} reviewer verified the recommendation-only Sprint 11S evidence and enterprise boundaries.`,
      }),
    }), `${role} review recorded.`);
  }

  async function decide(outcome: "recommend_separate_production_wide_authorization_review" | "extend_bounded_100_percent_cohort" | "stop_production_wide_progression") {
    if (!current) return;
    await act(`decision-${outcome}`, () => request(`/ai-bounded-full-production-outcomes/assessments/${current.id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        outcome, confirm_recommendation_only: true,
        note: outcome === "recommend_separate_production_wide_authorization_review"
          ? "Recommend only a separate unbounded Production-wide authorization design and review; do not widen runtime scope in Sprint 11S."
          : "Keep AI inside the currently governed bounded envelope while remediation or further evidence is required.",
      }),
    }), "Sprint 11S Admin outcome recorded.");
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11S · Bounded 100% Outcome</p>
      <h1 className="mt-3 text-3xl font-semibold">Enterprise Production Readiness Gate</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Measure one completed Sprint 11R bounded 100% cohort using source-ledger quality, human-review burden, business value and ten enterprise-operability controls. Fourteen independent reviewers plus a separate Admin are required. A positive result is recommendation-only.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[["Assessment", current?.status.replaceAll("_", " ") ?? "not created"], ["Measured rollout", current ? `${current.rollout_percentage}% bounded` : "100% bounded"], ["Reviews", current ? `${approved.size}/14` : "0/14"], ["Production-wide", "Not authorized"]].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold capitalize">{value}</p></div>)}
    </section>

    {!current && anchor && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Create the 11S measurement gate</h2><p className="mt-2 text-sm text-slate-600">Completed bounded-100% anchor: {anchor.authorization_key}. The new outcome ledger stores metrics and references only, never raw claim or provider content.</p><button disabled={busy !== null} onClick={() => void create()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create Sprint 11S assessment</button></section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">Enterprise evidence coverage</h2><p className="mt-1 text-sm text-slate-600">All ten categories must be present and passing before a positive recommendation is possible.</p></div>{current.status === "collecting" && <button disabled={busy !== null} onClick={() => void finalize()} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Finalize scorecard</button>}</div><div className="mt-4 grid gap-2 md:grid-cols-2">{enterpriseControls.map((control) => <div key={control} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm"><span>{control.replaceAll("_", " ")}</span><span className={`font-semibold ${enterprise.get(control) === true ? "text-emerald-700" : enterprise.has(control) ? "text-rose-700" : "text-slate-400"}`}>{enterprise.get(control) === true ? "pass" : enterprise.has(control) ? "fail" : "missing"}</span></div>)}</div></section>}

    {current && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">Fourteen independent reviews</h2><p className="mt-2 text-sm text-slate-600">Requester and final Admin must be distinct from every reviewer. Enterprise Architecture / Operational Resilience is the fourteenth role.</p><div className="mt-4 flex flex-wrap gap-2">{roles.map((role) => <button key={role} disabled={busy !== null || approved.has(role) || !["review_ready", "decision_ready"].includes(current.status)} onClick={() => void approve(role)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role.replaceAll("_", " ")} approve</button>)}</div>{current.status === "decision_ready" && <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5"><button disabled={busy !== null} onClick={() => void decide("recommend_separate_production_wide_authorization_review")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Recommend separate Production-wide review</button><button disabled={busy !== null} onClick={() => void decide("extend_bounded_100_percent_cohort")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Extend bounded 100%</button><button disabled={busy !== null} onClick={() => void decide("stop_production_wide_progression")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Stop progression</button></div>}{current.failure_reasons.length > 0 && <p className="mt-4 text-sm text-rose-700">Failed controls: {current.failure_reasons.join(", ")}</p>}{current.assessment_hash && <p className="mt-4 break-all font-mono text-[10px] text-slate-400">Assessment SHA-256: {current.assessment_hash}</p>}{current.decision_hash && <p className="mt-2 break-all font-mono text-[10px] text-slate-400">Decision SHA-256: {current.decision_hash}</p>}</section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Hard boundary:</strong> Sprint 11S never authorizes unbounded Production-wide AI, Restricted documents, new document classes, autonomous coverage/liability/causation/reserve/settlement/payment/recovery decisions, automatic authoritative claim facts, or removal of different-human review.</section>
  </div>;
}
