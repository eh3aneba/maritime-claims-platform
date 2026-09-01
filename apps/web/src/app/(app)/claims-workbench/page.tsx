"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type Priority = "routine" | "elevated" | "urgent" | "critical";
type Factor = {
  source_type: string; source_id: string; source_hash: string | null; category: string; label: string;
  weight: number; priority_hint: Priority; due_date: string | null;
  due_semantics: "authoritative_task_due" | "candidate_timebar" | "none"; href: string;
};
type Row = {
  claim_id: string; claim_reference: string; claim_type: string; claim_status: string; handler_id: string | null;
  priority: Priority; rank_score: number; ranking_version: string; rank_hash: string; requires_action: boolean;
  nearest_due_date: string | null; nearest_due_semantics: "authoritative_task_due" | "candidate_timebar" | "none";
  factors: Factor[]; source_state_time: string | null;
};
type Metrics = {
  claim_count: number; critical_count: number; urgent_count: number; elevated_count: number; due_soon_count: number;
  missing_evidence_count: number; conflict_count: number; financial_flag_count: number; pending_ai_review_count: number;
};
type Dashboard = { metrics: Metrics; rows: Row[]; ranking_version: string; operational_triage_only: boolean; claim_merits_decision: boolean };
type Page = { rows: Row[]; page: number; page_size: number; total: number; has_more: boolean };

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function label(value: string) { return value.replaceAll("_", " "); }
function shortHash(value: string | null) { return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—"; }
function priorityClass(priority: Priority) {
  if (priority === "critical") return "bg-rose-100 text-rose-800";
  if (priority === "urgent") return "bg-amber-100 text-amber-800";
  if (priority === "elevated") return "bg-cyan-100 text-cyan-800";
  return "bg-slate-100 text-slate-700";
}

export default function ClaimsWorkbenchPage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [priority, setPriority] = useState<"" | Priority>("");
  const [attention, setAttention] = useState("");
  const [dueSoon, setDueSoon] = useState(false);
  const [selected, setSelected] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: "1", page_size: "100" });
    if (priority) params.set("priority", priority);
    if (attention) params.set("attention_category", attention);
    if (dueSoon) params.set("overdue_or_due_soon", "true");
    return params.toString();
  }, [priority, attention, dueSoon]);

  const load = useCallback(async () => {
    try {
      const [d, q] = await Promise.all([
        request<Dashboard>("/claim-workbench"),
        request<Page>(`/claim-workbench/queue?${query}`),
      ]);
      setDashboard(d); setPage(q); setError(null);
      if (selected) {
        const refreshed = q.rows.find((row) => row.claim_id === selected.claim_id);
        if (refreshed) setSelected(refreshed);
      }
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load Claims Workbench."); }
  }, [query, selected]);

  useEffect(() => { void load(); }, [query]);

  const metrics = dashboard?.metrics;
  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Phase 12J · Portfolio operational triage</p>
      <h1 className="mt-3 text-3xl font-semibold">Claims Workbench</h1>
      <p className="mt-3 max-w-5xl text-sm leading-6 text-slate-300">A deterministic, source-linked queue showing which claims need operational attention next and why. Ranking is workflow triage only: it does not decide coverage, liability, causation, recoverability, reserve, settlement, payment or legal rights.</p>
    </section>

    <div className="rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-950">
      <strong>Decision boundary:</strong> no claim-merits decision · no autonomous mutation · candidate time-bars remain candidate dates · ranking version {dashboard?.ranking_version ?? "12J.1"}.
    </div>
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}

    <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      {[
        ["Claims", metrics?.claim_count ?? 0], ["Critical", metrics?.critical_count ?? 0], ["Urgent", metrics?.urgent_count ?? 0],
        ["Due ≤30d", metrics?.due_soon_count ?? 0], ["Missing evidence", metrics?.missing_evidence_count ?? 0],
        ["Pending AI review", metrics?.pending_ai_review_count ?? 0],
      ].map(([key, value]) => <div key={String(key)} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{key}</p><p className="mt-2 text-2xl font-semibold">{value}</p></div>)}
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-slate-600">Priority<select value={priority} onChange={(e) => setPriority(e.target.value as "" | Priority)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="">All</option><option value="critical">Critical</option><option value="urgent">Urgent</option><option value="elevated">Elevated</option><option value="routine">Routine</option></select></label>
        <label className="text-xs font-semibold text-slate-600">Attention<select value={attention} onChange={(e) => setAttention(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="">All</option><option value="candidate_timebar">Candidate time-bar</option><option value="handling_severity">Handling severity</option><option value="financial_flag">Financial flag</option><option value="missing_evidence">Missing evidence</option><option value="conflict">Conflict</option><option value="open_task">Open task</option><option value="pending_ai_review">Pending AI review</option><option value="governed_ai_attention">AI operations</option></select></label>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm"><input type="checkbox" checked={dueSoon} onChange={(e) => setDueSoon(e.target.checked)} /> Overdue / due within 30 days</label>
        <span className="ml-auto text-xs text-slate-500">{page?.total ?? 0} matching claims</span>
      </div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold">Ranked portfolio queue</h2><p className="mt-1 text-xs text-slate-500">Deterministic ranking from current source state; ties resolve by due date and claim reference.</p></div>
      <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">Claim</th><th className="px-4 py-3">Priority</th><th className="px-4 py-3">Score</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Nearest date</th><th className="px-4 py-3">Why</th><th className="px-4 py-3">Open</th></tr></thead><tbody>{page?.rows.map((row) => <tr key={row.claim_id} className="border-t border-slate-100 hover:bg-slate-50"><td className="px-4 py-3"><button onClick={() => setSelected(row)} className="text-left font-semibold text-slate-900 hover:underline">{row.claim_reference}</button><div className="mt-1 font-mono text-xs text-slate-400">{shortHash(row.rank_hash)}</div></td><td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${priorityClass(row.priority)}`}>{row.priority}</span></td><td className="px-4 py-3 font-semibold">{row.rank_score}</td><td className="px-4 py-3">{label(row.claim_status)}</td><td className="px-4 py-3">{row.nearest_due_date ?? "—"}{row.nearest_due_date && <div className="mt-1 text-xs text-slate-500">{row.nearest_due_semantics === "candidate_timebar" ? "candidate date" : "task due date"}</div>}</td><td className="px-4 py-3"><div className="flex max-w-xl flex-wrap gap-1">{row.factors.slice(0, 4).map((factor) => <span key={`${factor.source_type}-${factor.source_id}`} className="rounded-full bg-slate-100 px-2 py-1 text-xs">{factor.label}</span>)}</div></td><td className="px-4 py-3"><Link href={`/claims/${row.claim_id}`} className="text-xs font-semibold text-cyan-800 hover:underline">Claim workspace</Link></td></tr>)}</tbody></table></div>
    </section>

    {selected && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Ranking lineage</p><h2 className="mt-1 text-xl font-semibold">{selected.claim_reference}</h2><p className="mt-1 text-xs text-slate-500">Rank hash {selected.rank_hash} · contract {selected.ranking_version}</p></div><button onClick={() => setSelected(null)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold">Close</button></div>
      <div className="mt-5 space-y-3">{selected.factors.map((factor) => <div key={`${factor.source_type}-${factor.source_id}`} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold">{factor.label}</p><p className="mt-1 text-xs text-slate-500">{label(factor.source_type)} · {label(factor.category)} · weight {factor.weight}</p></div><Link href={factor.href} className="rounded-lg border border-cyan-300 px-3 py-2 text-xs font-semibold text-cyan-800">Open source workflow</Link></div><div className="mt-3 grid gap-2 text-xs text-slate-500 md:grid-cols-3"><div><span className="font-semibold">Source ID</span><p className="mt-1 font-mono break-all">{factor.source_id}</p></div><div><span className="font-semibold">Source hash</span><p className="mt-1 font-mono">{shortHash(factor.source_hash)}</p></div><div><span className="font-semibold">Date semantics</span><p className="mt-1">{label(factor.due_semantics)}{factor.due_date ? ` · ${factor.due_date}` : ""}</p></div></div></div>)}</div>
    </section>}
  </div>;
}
