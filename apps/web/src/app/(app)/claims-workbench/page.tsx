"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { API_BASE, ApiError } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18n";

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
type T = (key: TranslationKey, values?: Record<string, string | number>) => string;

const priorityKeys: Record<Priority, TranslationKey> = {
  critical: "priority.critical",
  urgent: "priority.urgent",
  elevated: "priority.elevated",
  routine: "priority.routine",
};
const attentionKeys: Record<string, TranslationKey> = {
  candidate_timebar: "attention.candidate_timebar",
  handling_severity: "attention.handling_severity",
  financial_flag: "attention.financial_flag",
  missing_evidence: "attention.missing_evidence",
  conflict: "attention.conflict",
  open_task: "attention.open_task",
  pending_ai_review: "attention.pending_ai_review",
  governed_ai_attention: "attention.governed_ai_attention",
};
const factorKeys: Record<string, TranslationKey> = {
  candidate_timebar: "factor.candidate_timebar",
  handling_severity: "factor.handling_severity",
  financial_flag: "factor.financial_flag",
  missing_evidence: "factor.missing_evidence",
  conflict: "factor.conflict",
  open_task: "factor.open_task",
  pending_ai_review: "factor.pending_ai_review",
  governed_ai_attention: "factor.governed_ai_attention",
};
const dueKeys: Record<Factor["due_semantics"], TranslationKey> = {
  authoritative_task_due: "due.authoritative_task_due",
  candidate_timebar: "due.candidate_timebar",
  none: "due.none",
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function fallbackLabel(value: string) { return value.replaceAll("_", " "); }
function shortHash(value: string | null) { return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—"; }
function priorityClass(priority: Priority) {
  if (priority === "critical") return "bg-rose-100 text-rose-800";
  if (priority === "urgent") return "bg-amber-100 text-amber-800";
  if (priority === "elevated") return "bg-cyan-100 text-cyan-800";
  return "bg-slate-100 text-slate-700";
}
function translatedAttention(value: string, t: T) { return attentionKeys[value] ? t(attentionKeys[value]) : fallbackLabel(value); }
function factorLabel(factor: Factor, t: T) {
  const key = factorKeys[factor.category];
  if (!key) return factor.label;
  return factor.due_date ? `${t(key)}: ${factor.due_date}` : t(key);
}

export default function ClaimsWorkbenchPage() {
  const { t } = useLocale();
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
    } catch (err) { setError(err instanceof ApiError ? err.detail : t("workbench.loadError")); }
  }, [query, selected, t]);

  useEffect(() => { void load(); }, [query]);

  const metrics = dashboard?.metrics;
  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">{t("workbench.phase")}</p>
      <h1 className="mt-3 text-3xl font-semibold">{t("workbench.title")}</h1>
      <p className="mt-3 max-w-5xl text-sm leading-6 text-slate-300">{t("workbench.description")}</p>
    </section>

    <div className="rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-950">
      <strong>{t("workbench.boundaryTitle")}</strong> {t("workbench.boundaryBody", { version: dashboard?.ranking_version ?? "12J.1" })}
    </div>
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}

    <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      {[
        [t("workbench.metric.claims"), metrics?.claim_count ?? 0], [t("workbench.metric.critical"), metrics?.critical_count ?? 0], [t("workbench.metric.urgent"), metrics?.urgent_count ?? 0],
        [t("workbench.metric.due30"), metrics?.due_soon_count ?? 0], [t("workbench.metric.missingEvidence"), metrics?.missing_evidence_count ?? 0],
        [t("workbench.metric.pendingAi"), metrics?.pending_ai_review_count ?? 0],
      ].map(([key, value]) => <div key={String(key)} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{key}</p><p className="mt-2 text-2xl font-semibold" dir="ltr">{value}</p></div>)}
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-slate-600">{t("workbench.filter.priority")}<select value={priority} onChange={(e) => setPriority(e.target.value as "" | Priority)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="">{t("common.all")}</option><option value="critical">{t("priority.critical")}</option><option value="urgent">{t("priority.urgent")}</option><option value="elevated">{t("priority.elevated")}</option><option value="routine">{t("priority.routine")}</option></select></label>
        <label className="text-xs font-semibold text-slate-600">{t("workbench.filter.attention")}<select value={attention} onChange={(e) => setAttention(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="">{t("common.all")}</option>{Object.keys(attentionKeys).map((value) => <option key={value} value={value}>{translatedAttention(value, t)}</option>)}</select></label>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm"><input type="checkbox" checked={dueSoon} onChange={(e) => setDueSoon(e.target.checked)} /> {t("workbench.filter.dueSoon")}</label>
        <span className="ms-auto text-xs text-slate-500">{t("workbench.matching", { count: page?.total ?? 0 })}</span>
      </div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold">{t("workbench.queueTitle")}</h2><p className="mt-1 text-xs text-slate-500">{t("workbench.queueHelp")}</p></div>
      <div className="overflow-x-auto"><table className="min-w-full text-start text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">{t("workbench.column.claim")}</th><th className="px-4 py-3">{t("workbench.column.priority")}</th><th className="px-4 py-3">{t("workbench.column.score")}</th><th className="px-4 py-3">{t("workbench.column.status")}</th><th className="px-4 py-3">{t("workbench.column.nearestDate")}</th><th className="px-4 py-3">{t("workbench.column.why")}</th><th className="px-4 py-3">{t("workbench.column.open")}</th></tr></thead><tbody>{page?.rows.map((row) => <tr key={row.claim_id} className="border-t border-slate-100 hover:bg-slate-50"><td className="px-4 py-3"><button onClick={() => setSelected(row)} className="font-semibold text-slate-900 hover:underline" dir="ltr">{row.claim_reference}</button><div className="mt-1 font-mono text-xs text-slate-400" dir="ltr">{shortHash(row.rank_hash)}</div></td><td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${priorityClass(row.priority)}`}>{t(priorityKeys[row.priority])}</span></td><td className="px-4 py-3 font-semibold" dir="ltr">{row.rank_score}</td><td className="px-4 py-3">{fallbackLabel(row.claim_status)}</td><td className="px-4 py-3"><span dir="ltr">{row.nearest_due_date ?? "—"}</span>{row.nearest_due_date && <div className="mt-1 text-xs text-slate-500">{row.nearest_due_semantics === "candidate_timebar" ? t("workbench.candidateDate") : t("workbench.taskDueDate")}</div>}</td><td className="px-4 py-3"><div className="flex max-w-xl flex-wrap gap-1">{row.factors.slice(0, 4).map((factor) => <span key={`${factor.source_type}-${factor.source_id}`} className="rounded-full bg-slate-100 px-2 py-1 text-xs">{factorLabel(factor, t)}</span>)}</div></td><td className="px-4 py-3"><Link href={`/claims/${row.claim_id}`} className="text-xs font-semibold text-cyan-800 hover:underline">{t("workbench.claimWorkspace")}</Link></td></tr>)}</tbody></table></div>
    </section>

    {selected && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t("workbench.lineage")}</p><h2 className="mt-1 text-xl font-semibold" dir="ltr">{selected.claim_reference}</h2><p className="mt-1 text-xs text-slate-500">{t("workbench.rankHash", { hash: selected.rank_hash, version: selected.ranking_version })}</p></div><button onClick={() => setSelected(null)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold">{t("common.close")}</button></div>
      <div className="mt-5 space-y-3">{selected.factors.map((factor) => <div key={`${factor.source_type}-${factor.source_id}`} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-semibold">{factorLabel(factor, t)}</p><p className="mt-1 text-xs text-slate-500">{fallbackLabel(factor.source_type)} · {translatedAttention(factor.category, t)} · {t("workbench.weight", { weight: factor.weight })}</p></div><Link href={factor.href} className="rounded-lg border border-cyan-300 px-3 py-2 text-xs font-semibold text-cyan-800">{t("workbench.openSource")}</Link></div><div className="mt-3 grid gap-2 text-xs text-slate-500 md:grid-cols-3"><div><span className="font-semibold">{t("workbench.sourceId")}</span><p className="mt-1 break-all font-mono" dir="ltr">{factor.source_id}</p></div><div><span className="font-semibold">{t("workbench.sourceHash")}</span><p className="mt-1 font-mono" dir="ltr">{shortHash(factor.source_hash)}</p></div><div><span className="font-semibold">{t("workbench.dateSemantics")}</span><p className="mt-1">{t(dueKeys[factor.due_semantics])}{factor.due_date ? <span dir="ltr"> · {factor.due_date}</span> : null}</p></div></div></div>)}</div>
    </section>}
  </div>;
}
