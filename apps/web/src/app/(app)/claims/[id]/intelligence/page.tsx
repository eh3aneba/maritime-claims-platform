"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type Decision = {
  id: string; action: "accept" | "edit" | "dismiss"; decision_number: number;
  edited_title: string | null; edited_description: string | null; edited_suggested_action: string | null;
  converted_task_id: string | null; note: string; decision_hash: string; decided_at: string;
};
type IntelligenceItem = {
  id: string; item_key: string; category: string; title: string; description: string; severity: string;
  urgency_score: number; evidential_value_score: number; rank_score: number; rationale: string;
  source_refs: Array<Record<string, unknown>>; action_type: string | null; suggested_action: string | null;
  item_hash: string; latest_decision: Decision | null;
};
type Snapshot = {
  id: string; snapshot_version: number; engine_version: string; source_state_hash: string; snapshot_hash: string;
  summary: Record<string, unknown>; generated_at: string; items: IntelligenceItem[];
};
type Dashboard = { claim_id: string; snapshot: Snapshot | null; disclaimer: string };

const sections = [
  ["incident_summary", "Executive claim snapshot"],
  ["chronology", "Chronology"],
  ["machinery_context", "Machinery context"],
  ["evidence_available", "Evidence available"],
  ["missing_evidence", "Missing evidence"],
  ["conflict", "Conflicts"],
  ["hypothesis", "Technical hypotheses"],
  ["issue_flag", "Issue flags"],
  ["financial_lead", "Financial / adjustment leads"],
  ["recovery_lead", "Recovery leads"],
  ["deadline_lead", "Deadlines / time-bar leads"],
  ["next_action", "Recommended next actions"],
] as const;

const severityClass: Record<string, string> = {
  critical: "border-rose-300 bg-rose-50 text-rose-900",
  high: "border-amber-300 bg-amber-50 text-amber-950",
  medium: "border-sky-200 bg-sky-50 text-sky-950",
  low: "border-slate-200 bg-slate-50 text-slate-800",
  info: "border-slate-200 bg-white text-slate-800",
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function pretty(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value).replaceAll("_", " ");
}

export default function ClaimIntelligencePage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try { setData(await request<Dashboard>(`/claims/${id}/intelligence`)); setError(""); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Claims Intelligence could not be loaded."); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const map = new Map<string, IntelligenceItem[]>();
    for (const item of data?.snapshot?.items ?? []) map.set(item.category, [...(map.get(item.category) ?? []), item]);
    return map;
  }, [data]);

  async function build() {
    setBusy("build"); setError(""); setMessage("");
    try {
      const snapshot = await request<Snapshot>(`/claims/${id}/intelligence/build`, { method: "POST" });
      setMessage(`Intelligence snapshot v${snapshot.snapshot_version} is ready.`);
      await load();
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Intelligence snapshot could not be built."); }
    finally { setBusy(null); }
  }

  async function decide(item: IntelligenceItem, action: "accept" | "edit" | "dismiss", convertToTask = false) {
    let edited_suggested_action: string | undefined;
    let edited_title: string | undefined;
    if (action === "edit") {
      edited_title = window.prompt("Edit the intelligence title", item.latest_decision?.edited_title ?? item.title) ?? undefined;
      if (!edited_title) return;
      if (item.suggested_action) {
        edited_suggested_action = window.prompt("Edit the suggested handler action", item.latest_decision?.edited_suggested_action ?? item.suggested_action) ?? undefined;
      }
    }
    const note = window.prompt(
      action === "dismiss" ? "Why is this intelligence not relevant?" : "Add the handler review note",
      action === "accept" ? "Reviewed against the cited sources." : "Human-reviewed intelligence decision.",
    );
    if (!note || note.trim().length < 5) return;
    setBusy(item.id); setError(""); setMessage("");
    try {
      await request(`/claims/${id}/intelligence/items/${item.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ action, note, edited_title, edited_suggested_action, convert_to_task: convertToTask }),
      });
      setMessage(convertToTask ? "Human decision recorded and a controlled claim task was created." : "Human intelligence decision recorded.");
      await load();
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Decision could not be recorded."); }
    finally { setBusy(null); }
  }

  const snapshot = data?.snapshot ?? null;
  const summary = snapshot?.summary ?? {};

  return <div className="space-y-7">
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claim</Link>
        <p className="mt-5 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">Phase 12A · Claims Intelligence</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Source-linked claim intelligence</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">One reviewable view across chronology, available and missing evidence, conflicts, marine issue flags, financial/recovery leads, deadlines and handler actions. Every material item carries lineage and remains non-authoritative until human review.</p>
      </div>
      <button disabled={busy !== null} onClick={() => void build()} className="primary-button disabled:opacity-40">{snapshot ? "Refresh intelligence" : "Build intelligence"}</button>
    </div>

    {error ? <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : null}
    {message ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{message}</div> : null}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
      <strong>Human decision boundary:</strong> {data?.disclaimer ?? "This workspace is decision support only and never makes authoritative claim decisions."}
    </section>

    {!snapshot ? <section className="panel p-8 text-center"><h2 className="text-lg font-semibold">No intelligence snapshot yet</h2><p className="mt-2 text-sm text-slate-500">Build the first snapshot to synchronize current rules, chronology and source-linked issue spotting.</p></section> : <>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        {[
          ["Snapshot", `v${snapshot.snapshot_version}`],
          ["Missing evidence", pretty(summary.missing_evidence_count)],
          ["Open conflicts", pretty(summary.open_conflict_count)],
          ["Hypotheses", pretty(summary.hypothesis_count)],
          ["Financial / recovery", pretty(summary.financial_recovery_lead_count)],
          ["Next actions", pretty(summary.next_action_count)],
        ].map(([label, value]) => <div key={label} className="panel p-4"><p className="metric-label">{label}</p><p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p></div>)}
      </section>

      {sections.map(([category, label]) => {
        const items = grouped.get(category) ?? [];
        if (!items.length) return null;
        return <section key={category} className="panel p-6">
          <div className="flex items-center justify-between gap-4"><div><h2 className="section-title">{label}</h2><p className="section-subtitle">{items.length} source-linked item{items.length === 1 ? "" : "s"}</p></div></div>
          <div className="mt-5 space-y-4">
            {items.map((item) => {
              const displayTitle = item.latest_decision?.edited_title ?? item.title;
              const displayDescription = item.latest_decision?.edited_description ?? item.description;
              const displayAction = item.latest_decision?.edited_suggested_action ?? item.suggested_action;
              return <article key={item.id} className={`rounded-xl border p-5 ${severityClass[item.severity] ?? severityClass.info}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-current/15 px-2 py-0.5 text-[11px] font-semibold uppercase">{item.severity}</span><span className="text-[11px] font-semibold uppercase text-slate-500">Rank {item.rank_score}/100</span></div><h3 className="mt-2 text-base font-semibold">{displayTitle}</h3></div>
                  {item.latest_decision ? <span className="rounded-full bg-white/70 px-2.5 py-1 text-xs font-semibold capitalize">Human: {item.latest_decision.action}{item.latest_decision.converted_task_id ? " · task created" : ""}</span> : <span className="rounded-full bg-white/70 px-2.5 py-1 text-xs font-semibold">Candidate</span>}
                </div>
                <p className="mt-3 text-sm leading-6">{displayDescription}</p>
                <p className="mt-3 text-xs leading-5 opacity-80"><strong>Why surfaced:</strong> {item.rationale}</p>
                {displayAction ? <div className="mt-3 rounded-lg border border-current/10 bg-white/55 p-3 text-sm"><strong>Suggested handler action:</strong> {displayAction}</div> : null}
                <details className="mt-3 rounded-lg bg-white/55 px-3 py-2 text-xs"><summary className="cursor-pointer font-semibold">Source lineage · {item.source_refs.length} reference{item.source_refs.length === 1 ? "" : "s"}</summary><div className="mt-2 space-y-2 font-mono text-[11px]">{item.source_refs.map((ref, index) => <div key={index} className="break-all rounded bg-white/70 p-2">{JSON.stringify(ref)}</div>)}</div><p className="mt-2 break-all text-[10px] text-slate-500">Item SHA-256: {item.item_hash}</p></details>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button disabled={busy !== null} onClick={() => void decide(item, "accept")} className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Accept</button>
                  {displayAction ? <button disabled={busy !== null} onClick={() => void decide(item, "accept", true)} className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Accept + create task</button> : null}
                  <button disabled={busy !== null} onClick={() => void decide(item, "edit")} className="rounded-lg border border-current/20 bg-white/70 px-3 py-2 text-xs font-semibold disabled:opacity-40">Edit</button>
                  <button disabled={busy !== null} onClick={() => void decide(item, "dismiss")} className="rounded-lg border border-current/20 bg-white/70 px-3 py-2 text-xs font-semibold disabled:opacity-40">Dismiss</button>
                </div>
                {item.latest_decision ? <p className="mt-3 text-[11px] opacity-70">Latest review: #{item.latest_decision.decision_number} · {new Date(item.latest_decision.decided_at).toLocaleString()} · {item.latest_decision.note}</p> : null}
              </article>;
            })}
          </div>
        </section>;
      })}

      <section className="rounded-xl border border-slate-200 bg-white p-4 text-[11px] text-slate-500">
        <p>Engine {snapshot.engine_version} · generated {new Date(snapshot.generated_at).toLocaleString()}</p>
        <p className="mt-1 break-all font-mono">Source-state SHA-256: {snapshot.source_state_hash}</p>
        <p className="mt-1 break-all font-mono">Snapshot SHA-256: {snapshot.snapshot_hash}</p>
      </section>
    </>}
  </div>;
}
