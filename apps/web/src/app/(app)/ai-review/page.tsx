"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  bulkApproveAIExtractions,
  getAIReviewDetail,
  getAISourcePreview,
  listAIReview,
  reviewAIExtraction,
} from "@/lib/api";
import type { AIReviewDetail, AIReviewItem, AIReviewStatus, AISemanticKind, AISourcePreview } from "@/lib/types";

function humanField(path: string) {
  return path
    .replace(/\[(\d+)\]/g, " $1")
    .split(".")
    .map((part) => part.replaceAll("_", " "))
    .join(" · ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function editValue(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function parseEditedValue(original: unknown, value: string): unknown {
  if (typeof original === "boolean") {
    if (value.trim().toLowerCase() === "true" || value.trim().toLowerCase() === "yes") return true;
    if (value.trim().toLowerCase() === "false" || value.trim().toLowerCase() === "no") return false;
  }
  if (typeof original === "number") {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) return parsed;
  }
  if (typeof original === "object" && original !== null) {
    try { return JSON.parse(value); } catch { return value; }
  }
  return value;
}

const semanticTone: Record<AISemanticKind, string> = {
  fact: "border-cyan-200 bg-cyan-50 text-cyan-800",
  opinion: "border-amber-200 bg-amber-50 text-amber-800",
  inference: "border-violet-200 bg-violet-50 text-violet-800",
};

const reviewTone: Record<AIReviewStatus, string> = {
  pending: "border-slate-200 bg-slate-50 text-slate-700",
  approved: "border-emerald-200 bg-emerald-50 text-emerald-700",
  edited: "border-blue-200 bg-blue-50 text-blue-700",
  rejected: "border-red-200 bg-red-50 text-red-700",
};

export default function AIReviewPage() {
  const [claimId, setClaimId] = useState("");
  const [queryReady, setQueryReady] = useState(false);
  const [items, setItems] = useState<AIReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<AIReviewStatus | "all">("pending");
  const [semanticFilter, setSemanticFilter] = useState<AISemanticKind | "all">("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [reviewReasons, setReviewReasons] = useState<Record<string, string>>({});
  const [source, setSource] = useState<Record<string, AISourcePreview | undefined>>({});
  const [sourceOpen, setSourceOpen] = useState<string | null>(null);
  const [history, setHistory] = useState<Record<string, AIReviewDetail | undefined>>({});
  const [historyOpen, setHistoryOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("review_status", statusFilter);
      params.set("limit", "200");
      if (semanticFilter !== "all") params.set("semantic_kind", semanticFilter);
      if (claimId) params.set("claim_id", claimId);
      const response = await listAIReview(params);
      setItems(response.items);
      setTotal(response.total);
      setSelected((current) => current.filter((id) => response.items.some((item) => item.extraction_id === id && item.bulk_approvable)));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "AI review queue could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setClaimId(new URLSearchParams(window.location.search).get("claim_id") ?? "");
    setQueryReady(true);
  }, []);

  useEffect(() => { if (queryReady) load(); }, [statusFilter, semanticFilter, claimId, queryReady]);

  const bulkEligible = useMemo(() => items.filter((item) => item.bulk_approvable), [items]);

  async function review(item: AIReviewItem, action: "approve" | "edit" | "reject") {
    setWorking(true);
    setError("");
    try {
      const payload: { action: "approve" | "edit" | "reject"; value?: unknown; reason?: string } = { action };
      if (action === "edit") payload.value = parseEditedValue(item.normalized_value ?? item.ai_value, editText);
      const itemReason = reviewReasons[item.extraction_id]?.trim();
      if (itemReason) payload.reason = itemReason;
      await reviewAIExtraction(item.extraction_id, payload);
      setEditing(null);
      setEditText("");
      setReviewReasons((current) => { const next = { ...current }; delete next[item.extraction_id]; return next; });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Review action could not be saved.");
    } finally {
      setWorking(false);
    }
  }

  async function toggleSource(item: AIReviewItem) {
    if (sourceOpen === item.extraction_id) {
      setSourceOpen(null);
      return;
    }
    setSourceOpen(item.extraction_id);
    if (!source[item.extraction_id]) {
      try {
        const preview = await getAISourcePreview(item.extraction_id);
        setSource((current) => ({ ...current, [item.extraction_id]: preview }));
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Source preview could not be loaded.");
      }
    }
  }

  async function toggleHistory(item: AIReviewItem) {
    if (historyOpen === item.extraction_id) {
      setHistoryOpen(null);
      return;
    }
    setHistoryOpen(item.extraction_id);
    if (!history[item.extraction_id]) {
      try {
        const detail = await getAIReviewDetail(item.extraction_id);
        setHistory((current) => ({ ...current, [item.extraction_id]: detail }));
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Review history could not be loaded.");
      }
    }
  }

  async function bulkApprove() {
    if (!selected.length) return;
    setWorking(true);
    setError("");
    try {
      await bulkApproveAIExtractions(selected, "Bulk-approved after source-linked metadata review.");
      setSelected([]);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Bulk approval could not be completed.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <p className="eyebrow">Human-in-the-loop</p>
          <h1 className="page-title">AI Review</h1>
          <p className="page-subtitle">Approve, correct or reject AI extraction candidates. Only explicit human actions can promote facts into the authoritative claim-facts layer.</p>
        </div>
        {selected.length ? <button disabled={working} onClick={bulkApprove} className="primary-button">Approve selected ({selected.length})</button> : null}
      </div>

      {claimId ? <div className="mt-5 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-900">Filtered to one claim. <Link href="/ai-review" className="font-semibold underline">Show organization queue</Link></div> : null}
      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="panel mt-6 p-4">
        <div className="grid gap-3 md:grid-cols-[220px_220px_1fr_auto] md:items-end">
          <label><span className="label">Review status</span><select className="field" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as AIReviewStatus | "all")}><option value="pending">Pending</option><option value="approved">Approved</option><option value="edited">Edited</option><option value="rejected">Rejected</option><option value="all">All</option></select></label>
          <label><span className="label">Evidence type</span><select className="field" value={semanticFilter} onChange={(e) => setSemanticFilter(e.target.value as AISemanticKind | "all")}><option value="all">All</option><option value="fact">Facts</option><option value="opinion">Opinions</option><option value="inference">Inferences</option></select></label>
          <div className="text-sm text-slate-500">{loading ? "Loading review queue…" : `${total} extraction candidate${total === 1 ? "" : "s"}`}{statusFilter === "pending" && bulkEligible.length ? ` · ${bulkEligible.length} eligible for cautious bulk approval` : ""}</div>
          {bulkEligible.length ? <button className="secondary-button" onClick={() => setSelected(selected.length === bulkEligible.length ? [] : bulkEligible.map((item) => item.extraction_id))}>{selected.length === bulkEligible.length ? "Clear selection" : "Select eligible"}</button> : null}
        </div>
      </section>

      <div className="mt-5 space-y-4">
        {!loading && items.length === 0 ? <div className="panel py-16 text-center"><p className="text-sm font-semibold text-slate-800">No extraction candidates in this view.</p><p className="mt-2 text-sm text-slate-500">AI-generated values appear here only after document intelligence has completed.</p></div> : null}
        {items.map((item) => {
          const currentSource = source[item.extraction_id];
          const isEditing = editing === item.extraction_id;
          const checked = selected.includes(item.extraction_id);
          return (
            <article key={item.extraction_id} className="panel overflow-hidden">
              <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(260px,0.9fr)_auto]">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    {item.bulk_approvable ? <input aria-label="Select for bulk approval" type="checkbox" checked={checked} onChange={() => setSelected((current) => current.includes(item.extraction_id) ? current.filter((id) => id !== item.extraction_id) : [...current, item.extraction_id])} className="h-4 w-4" /> : null}
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${semanticTone[item.semantic_kind]}`}>{item.semantic_kind}</span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${reviewTone[item.human_status]}`}>{item.human_status}</span>
                    <span className="text-xs font-medium text-slate-400">{Math.round(Number(item.confidence) * 100)}% confidence</span>
                  </div>
                  <h2 className="mt-3 text-base font-semibold text-slate-950">{humanField(item.field_path)}</h2>
                  <p className="mt-1 text-xs text-slate-400">{item.field_path}</p>
                  <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">AI candidate</p><p className="mt-2 break-words text-sm font-semibold text-slate-900">{displayValue(item.normalized_value ?? item.ai_value)}</p></div>
                  {item.human_status !== "pending" ? <div className="mt-3 text-xs text-slate-500">Human-approved value: <span className="font-semibold text-slate-700">{displayValue(item.approved_value)}</span></div> : null}
                </div>

                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Evidence source</p>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{item.source_quote ? `“${item.source_quote}”` : "No source quote supplied."}</p>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500"><span>{item.document_name}</span><span>{item.source_locator_type && item.source_locator_value ? `${item.source_locator_type}: ${item.source_locator_value}` : "Locator unavailable"}</span><span className={item.source_verified ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>{item.source_verified ? "Source verified" : "Manual source check required"}</span></div>
                  {item.validation_warnings?.length ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">{item.validation_warnings.join(" ")}</div> : null}
                  {!item.source_verified && item.human_status === "pending" ? <label className="mt-3 block"><span className="label">Manual verification reason</span><textarea className="field resize-y" rows={2} value={reviewReasons[item.extraction_id] ?? ""} onChange={(e) => setReviewReasons((current) => ({ ...current, [item.extraction_id]: e.target.value }))} placeholder="Required before approving or editing an unverified source citation." /></label> : null}
                  <div className="mt-3 flex flex-wrap gap-4"><button onClick={() => toggleSource(item)} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">{sourceOpen === item.extraction_id ? "Hide source context" : "View source context"}</button><button onClick={() => toggleHistory(item)} className="text-xs font-semibold text-slate-600 hover:text-slate-900">{historyOpen === item.extraction_id ? "Hide review history" : "Review history"}</button></div>
                </div>

                <div className="flex min-w-[170px] flex-col gap-2 lg:items-stretch">
                  <Link href={`/claims/${item.claim_id}`} className="text-sm font-semibold text-slate-900 hover:text-cyan-800">{item.claim_reference}</Link>
                  <span className="text-xs text-slate-500">{item.vessel_name}</span>
                  {item.human_status === "pending" ? <div className="mt-2 grid gap-2"><button disabled={working} onClick={() => review(item, "approve")} className="secondary-button justify-center">Approve</button><button disabled={working} onClick={() => { setEditing(item.extraction_id); setEditText(editValue(item.normalized_value ?? item.ai_value)); }} className="secondary-button justify-center">Edit</button><button disabled={working} onClick={() => review(item, "reject")} className="rounded-lg border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-red-700 hover:bg-red-50">Reject</button></div> : null}
                </div>
              </div>

              {sourceOpen === item.extraction_id ? <div className="border-t border-slate-200 bg-slate-50 px-5 py-4"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Source segment</p>{currentSource ? <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-4 font-sans text-xs leading-6 text-slate-700">{currentSource.segment_text ?? "Source segment is unavailable."}</pre> : <p className="mt-3 text-sm text-slate-500">Loading source context…</p>}</div> : null}

              {historyOpen === item.extraction_id ? <div className="border-t border-slate-200 bg-white px-5 py-4"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Human review history</p>{history[item.extraction_id] ? <div className="mt-3 space-y-3">{history[item.extraction_id]!.feedback.length ? history[item.extraction_id]!.feedback.map((entry) => <div key={entry.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-semibold uppercase tracking-wide text-slate-700">{entry.action}</span><span className="text-xs text-slate-400">{new Date(entry.created_at).toLocaleString()}</span></div><p className="mt-2 text-sm text-slate-700">{entry.reviewer_name ?? entry.reviewer_email ?? "Reviewer unavailable"}</p><p className="mt-1 text-xs text-slate-500">Human value: {displayValue(entry.human_value)}</p>{entry.reason ? <p className="mt-2 text-xs leading-5 text-slate-600">Reason: {entry.reason}</p> : null}</div>) : <p className="text-sm text-slate-500">No human review actions recorded yet.</p>}{history[item.extraction_id]!.current_claim_fact ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">Current approved claim fact · version {history[item.extraction_id]!.current_claim_fact!.version}</div> : null}</div> : <p className="mt-3 text-sm text-slate-500">Loading review history…</p>}</div> : null}

              {isEditing ? <div className="border-t border-slate-200 bg-white px-5 py-5"><div className="grid gap-4 lg:grid-cols-[1fr_1fr_auto]"><label><span className="label">Corrected value</span><textarea className="field min-h-24 resize-y" value={editText} onChange={(e) => setEditText(e.target.value)} /></label><label><span className="label">Review reason</span><textarea className="field min-h-24 resize-y" value={reviewReasons[item.extraction_id] ?? ""} onChange={(e) => setReviewReasons((current) => ({ ...current, [item.extraction_id]: e.target.value }))} placeholder="Optional for verified sources; required if the source citation is unverified." /></label><div className="flex items-end gap-2"><button disabled={working} onClick={() => review(item, "edit")} className="primary-button">Save correction</button><button disabled={working} onClick={() => setEditing(null)} className="secondary-button">Cancel</button></div></div></div> : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
