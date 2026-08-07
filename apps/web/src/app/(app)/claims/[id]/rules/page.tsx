"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, evaluateClaimRules, getClaim, getClaimRules } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Claim, ClaimDocumentRequirement, ClaimRuleSummary, RequirementPriority } from "@/lib/types";

const priorityOrder: RequirementPriority[] = ["critical", "important", "supporting"];

function requirementTone(status: ClaimDocumentRequirement["status"]) {
  if (["received", "accepted", "under_review"].includes(status)) return "bg-emerald-50 text-emerald-700";
  if (status === "requested") return "bg-cyan-50 text-cyan-700";
  if (["rejected"].includes(status)) return "bg-red-50 text-red-700";
  return "bg-amber-50 text-amber-800";
}

function severityTone(severity: string) {
  if (severity === "critical") return "border-red-300 bg-red-50";
  if (severity === "high") return "border-orange-300 bg-orange-50";
  if (severity === "medium") return "border-amber-300 bg-amber-50";
  return "border-slate-200 bg-slate-50";
}

export default function ClaimRulesPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [summary, setSummary] = useState<ClaimRuleSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [claimData, rulesData] = await Promise.all([getClaim(id), getClaimRules(id)]);
      setClaim(claimData);
      setSummary(rulesData);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Rules could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [id]);

  async function evaluate() {
    setEvaluating(true);
    setError("");
    try {
      const result = await evaluateClaimRules(id);
      setSummary(result.summary);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Rules could not be evaluated.");
    } finally {
      setEvaluating(false);
    }
  }

  const grouped = useMemo(() => {
    const output = new Map<RequirementPriority, ClaimDocumentRequirement[]>();
    for (const priority of priorityOrder) output.set(priority, []);
    for (const requirement of summary?.requirements ?? []) output.get(requirement.priority)?.push(requirement);
    return output;
  }, [summary]);

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading claim rules…</div>;
  if (!claim || !summary) return <div className="panel p-6 text-sm text-red-700">{error || "Rules unavailable."}</div>;

  const readinessLabel = summary.readiness.state === "ready" ? "Ready" : summary.readiness.state === "limited" ? "Limited" : "Not ready";

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to {claim.vessel.name}</Link>
      <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <p className="eyebrow">{claim.claim_reference} · Ruleset {summary.ruleset_version}</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Requirements & rules</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">Deterministic decision-support rules. Missing documents and investigation flags are explainable and do not decide coverage or causation.</p>
        </div>
        <button onClick={evaluate} disabled={evaluating} className="primary-button">{evaluating ? "Evaluating…" : "Refresh rules"}</button>
      </div>

      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">Readiness</p><p className="metric-value">{summary.readiness.score}%</p><p className="mt-1 text-xs font-semibold text-slate-500">{readinessLabel}</p></div>
        <div className="panel p-5"><p className="metric-label">Critical missing</p><p className="metric-value">{summary.readiness.critical_missing_count}</p></div>
        <div className="panel p-5"><p className="metric-label">Important missing</p><p className="metric-value">{summary.readiness.important_missing_count}</p></div>
        <div className="panel p-5"><p className="metric-label">Active issues</p><p className="metric-value">{summary.issues.length}</p><p className="mt-1 text-xs text-slate-400">Evaluated {summary.evaluated_at ? formatDate(summary.evaluated_at) : "not yet"}</p></div>
      </section>

      {summary.readiness.blocking_items.length ? <section className="mt-5 rounded-xl border border-red-200 bg-red-50 p-5"><h2 className="text-sm font-semibold text-red-900">Blocking evidence</h2><p className="mt-1 text-xs leading-5 text-red-700">These Critical items keep the current-stage readiness state at Not ready.</p><div className="mt-3 flex flex-wrap gap-2">{summary.readiness.blocking_items.map((item) => <span key={item} className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-red-700 ring-1 ring-red-200">{item}</span>)}</div></section> : null}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,.75fr)]">
        <section className="panel p-6">
          <div><h2 className="section-title">Current-stage document requirements</h2><p className="section-subtitle">Requirements appear only when the claim stage and reviewed facts activate the underlying rule.</p></div>
          <div className="mt-5 space-y-6">
            {priorityOrder.map((priority) => {
              const items = grouped.get(priority) ?? [];
              if (!items.length) return null;
              return <div key={priority}><div className="mb-2 flex items-center gap-2"><h3 className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">{priority}</h3><span className="text-xs text-slate-400">{items.length}</span></div><div className="divide-y divide-slate-200 rounded-xl border border-slate-200">{items.map((item) => <div key={item.id} className="p-4"><div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start"><div><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-semibold text-slate-900">{item.document_label}</p><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ${requirementTone(item.status)}`}>{item.status.replaceAll("_", " ")}</span></div><p className="mt-2 text-xs leading-5 text-slate-500">{item.reason}</p></div><div className="shrink-0 text-right text-[11px] text-slate-400"><div>{item.rule_id} · v{item.rule_version}</div><div>From {item.required_from_status.replaceAll("_", " ")}</div></div></div></div>)}</div></div>;
            })}
            {!summary.requirements.length ? <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">No rules are active for the current stage yet. Advance to Triage or refresh after reviewed evidence changes.</div> : null}
          </div>
        </section>

        <section className="panel p-6">
          <h2 className="section-title">Investigation flags</h2>
          <p className="section-subtitle">Rules surface review topics; they do not determine causation, coverage or settlement.</p>
          <div className="mt-5 space-y-3">
            {summary.issues.map((issue) => <article key={issue.id} className={`rounded-xl border p-4 ${severityTone(issue.severity)}`}><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">{issue.category} · {issue.rule_id}</p><h3 className="mt-1 text-sm font-semibold text-slate-950">{issue.title}</h3></div><span className="rounded-full bg-white/80 px-2 py-1 text-[11px] font-bold uppercase text-slate-600">{issue.severity}</span></div><p className="mt-3 text-xs leading-5 text-slate-700">{issue.description}</p>{issue.explanation ? <div className="mt-3 rounded-lg bg-white/70 p-3"><p className="text-[11px] font-bold uppercase tracking-[.12em] text-slate-500">Why am I seeing this?</p><p className="mt-1 text-xs leading-5 text-slate-600">{issue.explanation}</p></div> : null}{issue.evidence ? <details className="mt-3 text-xs text-slate-600"><summary className="cursor-pointer font-semibold">Trigger data</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white/80 p-3 text-[11px]">{JSON.stringify(issue.evidence, null, 2)}</pre></details> : null}</article>)}
            {!summary.issues.length ? <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-7 text-center text-sm text-slate-500">No active rule-generated issues.</div> : null}
          </div>
        </section>
      </div>
    </div>
  );
}
