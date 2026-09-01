"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type Workflow = "document_processing" | "claim_qa_synthesis";
type Event = {
  id: string; workflow_type: Workflow; event_time: string; claim_id: string; document_id: string | null;
  document_type: string | null; authorization_id: string | null; authorization_hash: string | null;
  eligibility_decision_id: string | null; eligibility_policy_hash: string | null; eligibility_decision_hash: string | null;
  status: string; failure_code: string | null; fallback_used: boolean; provider_call_made: boolean;
  provider: string | null; model: string | null; prompt_bundle_version: string | null; schema_bundle_version: string | null;
  human_review_state: "pending" | "completed" | "not_applicable"; human_review_action: string | null;
  requested_by_id: string | null; reviewed_by_id: string | null; run_hash: string | null; review_hash: string | null;
  retrieval_run_id: string | null; question_hash: string | null; result_set_hash: string | null;
  input_hash: string | null; output_hash: string | null; answer_hash: string | null; source_count: number | null;
  output_candidate_count: number | null; human_edit_count: number | null; unsupported_output_count: number | null;
  source_grounded_output_count: number | null; source_grounding_total_count: number | null;
  input_chars: number | null; input_tokens: number | null; output_tokens: number | null; total_tokens: number | null;
  latency_ms: number | null; observed_provider_cost_microusd: number | null; requires_attention: boolean;
  attention_reasons: string[]; content_free: boolean;
};
type Page = { events: Event[]; page: number; page_size: number; total: number; has_more: boolean };
type Metrics = {
  event_count: number; document_processing_count: number; claim_qa_synthesis_count: number; provider_run_count: number;
  blocked_or_fallback_count: number; verification_failure_count: number; authorization_or_policy_block_count: number;
  pending_human_review_count: number; approve_count: number; edit_count: number; reject_count: number;
  unsupported_output_count: number; source_grounding_validity_bps: number | null; total_tokens: number;
  total_observed_provider_cost_microusd: number; mean_latency_ms: number | null; p95_latency_ms: number | null;
  requires_attention_count: number; failures_by_workflow: Record<string, number>; failures_by_model: Record<string, number>;
};
type Dashboard = { metrics: Metrics; recent_attention: Event[]; content_free_governance_plane: boolean; raw_claim_or_model_content_exposed: boolean };

type ReviewForm = {
  output_candidate_count: number; human_edit_count: number; unsupported_output_count: number;
  source_grounded_output_count: number; source_grounding_total_count: number; latency_ms: number;
  observed_provider_cost_microusd: number; evidence_reference: string; note: string;
};

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

function label(value: string | null | undefined) {
  return value ? value.replaceAll("_", " ") : "—";
}

function hash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—";
}

export default function AIOperationsPage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [events, setEvents] = useState<Page | null>(null);
  const [queue, setQueue] = useState<Page | null>(null);
  const [workflow, setWorkflow] = useState<"" | Workflow>("");
  const [status, setStatus] = useState("");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [claimId, setClaimId] = useState("");
  const [selected, setSelected] = useState<Event | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewForm>({
    output_candidate_count: 1, human_edit_count: 0, unsupported_output_count: 0,
    source_grounded_output_count: 1, source_grounding_total_count: 1, latency_ms: 1,
    observed_provider_cost_microusd: 0, evidence_reference: "artifact://ai-operations/operator-review",
    note: "Different-human operator reviewed this Production AI Decision Log entry against the controlled claim/document workspace.",
  });
  const [incident, setIncident] = useState({
    severity: "medium", category: "quality", evidence_reference: "artifact://ai-operations/operator-anomaly",
    note: "Operator identified a material governed-AI anomaly requiring the existing Production-wide incident workflow.",
  });

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: "1", page_size: "50" });
    if (workflow) params.set("workflow_type", workflow);
    if (status.trim()) params.set("status", status.trim());
    if (attentionOnly) params.set("requires_attention", "true");
    if (claimId.trim()) params.set("claim_id", claimId.trim());
    return params.toString();
  }, [workflow, status, attentionOnly, claimId]);

  const load = useCallback(async () => {
    try {
      const [d, e, q] = await Promise.all([
        request<Dashboard>("/ai-operations"),
        request<Page>(`/ai-operations/events?${query}`),
        request<Page>("/ai-operations/review-queue?page=1&page_size=20"),
      ]);
      setDashboard(d); setEvents(e); setQueue(q); setError(null);
      if (selected) {
        const refreshed = [...e.events, ...q.events].find((item) => item.id === selected.id && item.workflow_type === selected.workflow_type);
        if (refreshed) setSelected(refreshed);
      }
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not load AI Operations."); }
  }, [query, selected]);

  useEffect(() => { void load(); }, [query]);

  async function reviewEvent(action: "approve" | "edit" | "reject") {
    if (!selected || selected.workflow_type !== "document_processing") return;
    setBusy(`review-${action}`); setError(null); setMessage(null);
    try {
      const updated = await request<Event>(`/ai-operations/events/document_processing/${selected.id}/review`, {
        method: "POST", body: JSON.stringify({ ...review, human_review_action: action, confirm_different_human_review: true }),
      });
      setSelected(updated); setMessage(`Decision Log ${action} review recorded with immutable review lineage.`); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Review failed."); }
    finally { setBusy(null); }
  }

  async function handoffIncident() {
    if (!selected) return;
    setBusy("incident"); setError(null); setMessage(null);
    try {
      await request(`/ai-operations/events/${selected.workflow_type}/${selected.id}/incident`, {
        method: "POST", body: JSON.stringify({ ...incident, confirm_incident_handoff: true }),
      });
      setMessage("Governance anomaly handed to the existing Production-wide incident workflow."); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Incident handoff failed."); }
    finally { setBusy(null); }
  }

  async function exportData(format: "json" | "csv") {
    setBusy(`export-${format}`); setError(null);
    try {
      const filters: Record<string, unknown> = {};
      if (workflow) filters.workflow_type = workflow;
      if (status.trim()) filters.status = status.trim();
      if (attentionOnly) filters.requires_attention = true;
      if (claimId.trim()) filters.claim_id = claimId.trim();
      const response = await fetch(`${API_BASE}/ai-operations/export`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format, filters, max_rows: 5000 }),
      });
      if (!response.ok) throw new ApiError(response.status, "Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `ai-operations-content-free.${format}`; anchor.click();
      URL.revokeObjectURL(url); setMessage(`Content-free ${format.toUpperCase()} export generated and audited.`);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Export failed."); }
    finally { setBusy(null); }
  }

  const metrics = dashboard?.metrics;
  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Phase 12H · Governed AI observability</p>
      <h1 className="mt-3 text-3xl font-semibold">AI Decision Log / AI Operations</h1>
      <p className="mt-3 max-w-5xl text-sm leading-6 text-slate-300">One tenant-scoped operator console across Production Decision Logs and governed Claim Q&amp;A synthesis. This workspace exposes identifiers, hashes and operational metrics only—never raw prompts, questions, evidence passages, provider responses or synthesized answer text.</p>
    </section>

    {(message || error) && <div className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      {[
        ["Events", metrics?.event_count ?? 0], ["Needs attention", metrics?.requires_attention_count ?? 0],
        ["Pending reviews", metrics?.pending_human_review_count ?? 0], ["Blocked / fallback", metrics?.blocked_or_fallback_count ?? 0],
        ["Grounding failures", metrics?.verification_failure_count ?? 0], ["P95 latency", metrics?.p95_latency_ms ? `${metrics.p95_latency_ms} ms` : "—"],
      ].map(([k, v]) => <div key={String(k)} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{k}</p><p className="mt-2 text-2xl font-semibold">{v}</p></div>)}
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-slate-600">Workflow<select value={workflow} onChange={(e) => setWorkflow(e.target.value as "" | Workflow)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="">All</option><option value="document_processing">Document processing</option><option value="claim_qa_synthesis">Claim Q&amp;A synthesis</option></select></label>
        <label className="text-xs font-semibold text-slate-600">Status<input value={status} onChange={(e) => setStatus(e.target.value)} placeholder="completed / blocked" className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label>
        <label className="text-xs font-semibold text-slate-600">Claim ID<input value={claimId} onChange={(e) => setClaimId(e.target.value)} placeholder="UUID" className="mt-1 block w-72 rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm"><input type="checkbox" checked={attentionOnly} onChange={(e) => setAttentionOnly(e.target.checked)} /> Requires attention only</label>
        <div className="ml-auto flex gap-2"><button disabled={busy !== null} onClick={() => void exportData("csv")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">Export CSV</button><button disabled={busy !== null} onClick={() => void exportData("json")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">Export JSON</button></div>
      </div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold">Unified operational events</h2><p className="mt-1 text-xs text-slate-500">{events?.total ?? 0} matching events · deterministic newest-first ordering</p></div>
      <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">Time</th><th className="px-4 py-3">Workflow</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Claim</th><th className="px-4 py-3">Model</th><th className="px-4 py-3">Review</th><th className="px-4 py-3">Attention</th></tr></thead><tbody>{events?.events.map((event) => <tr key={`${event.workflow_type}-${event.id}`} onClick={() => { setSelected(event); setReview((r) => ({ ...r, latency_ms: event.latency_ms ?? 1, observed_provider_cost_microusd: event.observed_provider_cost_microusd ?? 0, evidence_reference: `artifact://ai-operations/review/${event.id}` })); }} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"><td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{new Date(event.event_time).toLocaleString()}</td><td className="px-4 py-3 font-medium">{label(event.workflow_type)}</td><td className="px-4 py-3">{label(event.status)}{event.failure_code && <div className="mt-1 text-xs text-rose-600">{label(event.failure_code)}</div>}</td><td className="px-4 py-3 font-mono text-xs">{event.claim_id.slice(0, 8)}…</td><td className="px-4 py-3">{event.model ?? "—"}</td><td className="px-4 py-3">{label(event.human_review_state)}{event.human_review_action && ` · ${event.human_review_action}`}</td><td className="px-4 py-3">{event.requires_attention ? <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">Review</span> : <span className="text-emerald-700">Clear</span>}</td></tr>)}</tbody></table></div>
    </section>

    <section className="grid gap-5 xl:grid-cols-2">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><div><h2 className="font-semibold">Different-human review queue</h2><p className="mt-1 text-xs text-slate-500">Production Decision Log only; synthesis runs remain observability-only.</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{queue?.total ?? 0} pending</span></div><div className="mt-4 space-y-2">{queue?.events.slice(0, 8).map((event) => <button key={event.id} onClick={() => setSelected(event)} className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-3 text-left text-sm hover:bg-slate-50"><span><span className="font-medium">{label(event.document_type)}</span><span className="ml-2 font-mono text-xs text-slate-500">{event.claim_id.slice(0, 8)}…</span></span><span className="text-xs text-amber-700">pending</span></button>)}</div></div>
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-semibold">Operational quality</h2><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div className="rounded-lg bg-slate-50 p-3">Approve <strong className="float-right">{metrics?.approve_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">Edit <strong className="float-right">{metrics?.edit_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">Reject <strong className="float-right">{metrics?.reject_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">Unsupported <strong className="float-right">{metrics?.unsupported_output_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">Grounding <strong className="float-right">{metrics?.source_grounding_validity_bps == null ? "—" : `${(metrics.source_grounding_validity_bps / 100).toFixed(2)}%`}</strong></div><div className="rounded-lg bg-slate-50 p-3">Tokens <strong className="float-right">{metrics?.total_tokens ?? 0}</strong></div></div></div>
    </section>

    {selected && <section className="rounded-2xl border border-cyan-200 bg-white p-6 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase text-cyan-700">Lineage drill-down</p><h2 className="mt-1 text-xl font-semibold">{label(selected.workflow_type)} · {label(selected.status)}</h2></div><div className="flex gap-2"><Link href={`/claims/${selected.claim_id}`} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">Open claim workspace</Link><button onClick={() => setSelected(null)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Close</button></div></div>
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4 text-xs"><div><span className="font-semibold text-slate-500">Authorization</span><p className="mt-1 font-mono break-all">{selected.authorization_id ?? "—"}</p></div><div><span className="font-semibold text-slate-500">Authorization hash</span><p className="mt-1 font-mono">{hash(selected.authorization_hash)}</p></div><div><span className="font-semibold text-slate-500">Policy hash</span><p className="mt-1 font-mono">{hash(selected.eligibility_policy_hash)}</p></div><div><span className="font-semibold text-slate-500">Result / run hash</span><p className="mt-1 font-mono">{hash(selected.run_hash ?? selected.result_set_hash)}</p></div><div><span className="font-semibold text-slate-500">Input hash</span><p className="mt-1 font-mono">{hash(selected.input_hash)}</p></div><div><span className="font-semibold text-slate-500">Output hash</span><p className="mt-1 font-mono">{hash(selected.output_hash)}</p></div><div><span className="font-semibold text-slate-500">Answer / review hash</span><p className="mt-1 font-mono">{hash(selected.answer_hash ?? selected.review_hash)}</p></div><div><span className="font-semibold text-slate-500">Bundle</span><p className="mt-1">{selected.prompt_bundle_version ?? "—"} · {selected.schema_bundle_version ?? "—"}</p></div></div>
      {selected.attention_reasons.length > 0 && <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Attention: {selected.attention_reasons.map(label).join(" · ")}</div>}

      {selected.workflow_type === "document_processing" && selected.human_review_state === "pending" && <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="font-semibold">Complete existing different-human review</h3><p className="mt-1 text-xs text-slate-500">Use the controlled claim/document workspace to verify these metrics before submitting. Requesters cannot review their own run.</p><div className="mt-3 grid gap-3 md:grid-cols-4">{(["output_candidate_count","human_edit_count","unsupported_output_count","source_grounded_output_count","source_grounding_total_count","latency_ms","observed_provider_cost_microusd"] as const).map((field) => <label key={field} className="text-xs font-semibold text-slate-600">{label(field)}<input type="number" min={0} value={review[field]} onChange={(e) => setReview({ ...review, [field]: Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal" /></label>)}</div><label className="mt-3 block text-xs font-semibold text-slate-600">Evidence reference<input value={review.evidence_reference} onChange={(e) => setReview({ ...review, evidence_reference: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><label className="mt-3 block text-xs font-semibold text-slate-600">Review note<textarea value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><div className="mt-3 flex gap-2">{(["approve","edit","reject"] as const).map((action) => <button key={action} disabled={busy !== null} onClick={() => void reviewEvent(action)} className={`rounded-lg px-4 py-2 text-sm font-semibold ${action === "approve" ? "bg-emerald-700 text-white" : action === "reject" ? "border border-rose-300 text-rose-700" : "border border-amber-300 text-amber-800"}`}>{action}</button>)}</div></div>}

      {selected.authorization_id && <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="font-semibold">Explicit incident handoff</h3><p className="mt-1 text-xs text-slate-500">This does not autonomously declare an incident. Submitting below is an explicit human action that reuses the existing Production-wide incident service.</p><div className="mt-3 grid gap-3 md:grid-cols-2"><label className="text-xs font-semibold text-slate-600">Severity<select value={incident.severity} onChange={(e) => setIncident({ ...incident, severity: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option>low</option><option>medium</option><option>high</option><option>critical</option></select></label><label className="text-xs font-semibold text-slate-600">Category<select value={incident.category} onChange={(e) => setIncident({ ...incident, category: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option>quality</option><option>cost</option><option>availability</option><option>reliability</option><option>privacy</option><option>security</option><option>cross_tenant</option><option>other</option></select></label></div><label className="mt-3 block text-xs font-semibold text-slate-600">Evidence reference<input value={incident.evidence_reference} onChange={(e) => setIncident({ ...incident, evidence_reference: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><label className="mt-3 block text-xs font-semibold text-slate-600">Incident note<textarea value={incident.note} onChange={(e) => setIncident({ ...incident, note: e.target.value })} className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><button disabled={busy !== null} onClick={() => void handoffIncident()} className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">Hand off to incident workflow</button></div>}
    </section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>Content-free governance boundary:</strong> AI Operations does not create AI authorization, widen provider/model/document permissions, expose raw claim/model content, persist transient Q&amp;A wording, change ClaimFact, or make coverage, liability, causation, recoverability, reserve, settlement or payment decisions.</section>
  </div>;
}
