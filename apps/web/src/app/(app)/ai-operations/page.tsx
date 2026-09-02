"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { API_BASE, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { aiLabel, aiT } from "@/lib/i18n-ai-operator";

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

function hash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—";
}

export default function AIOperationsPage() {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => aiT(locale, en, fa);
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
      setSelected((current) => {
        if (!current) return current;
        return [...e.events, ...q.events].find((item) => item.id === current.id && item.workflow_type === current.workflow_type) ?? current;
      });
    } catch (err) { setError(err instanceof ApiError ? err.detail : aiT(locale, "Could not load AI Operations.", "عملیات AI بارگذاری نشد.")); }
  }, [query, locale]);

  useEffect(() => { void load(); }, [load]);

  async function reviewEvent(action: "approve" | "edit" | "reject") {
    if (!selected || selected.workflow_type !== "document_processing") return;
    setBusy(`review-${action}`); setError(null); setMessage(null);
    try {
      const updated = await request<Event>(`/ai-operations/events/document_processing/${selected.id}/review`, {
        method: "POST", body: JSON.stringify({ ...review, human_review_action: action, confirm_different_human_review: true }),
      });
      setSelected(updated); setMessage(L(`Decision Log ${action} review recorded with immutable review lineage.`, `بازبینی ${aiLabel(locale, action)} در Decision Log با زنجیره بازبینی تغییرناپذیر ثبت شد.`)); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Review failed.", "بازبینی ناموفق بود.")); }
    finally { setBusy(null); }
  }

  async function handoffIncident() {
    if (!selected) return;
    setBusy("incident"); setError(null); setMessage(null);
    try {
      await request(`/ai-operations/events/${selected.workflow_type}/${selected.id}/incident`, {
        method: "POST", body: JSON.stringify({ ...incident, confirm_incident_handoff: true }),
      });
      setMessage(L("Governance anomaly handed to the existing Production-wide incident workflow.", "ناهنجاری حاکمیتی به جریان موجود incident در سطح Production تحویل شد.")); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Incident handoff failed.", "تحویل incident ناموفق بود.")); }
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
      URL.revokeObjectURL(url); setMessage(L(`Content-free ${format.toUpperCase()} export generated and audited.`, `خروجی ${format.toUpperCase()} بدون محتوای خام تولید و audit شد.`));
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Export failed.", "خروجی‌گیری ناموفق بود.")); }
    finally { setBusy(null); }
  }

  const metrics = dashboard?.metrics;
  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">{L("Phase 12H · Governed AI observability", "Phase 12H · مشاهده‌پذیری AI تحت حاکمیت")}</p>
      <h1 className="mt-3 text-3xl font-semibold">{L("AI Decision Log / AI Operations", "لاگ تصمیم AI / عملیات AI")}</h1>
      <p className="mt-3 max-w-5xl text-sm leading-6 text-slate-300">{L("One tenant-scoped operator console across Production Decision Logs and governed Claim Q&A synthesis. This workspace exposes identifiers, hashes and operational metrics only—never raw prompts, questions, evidence passages, provider responses or synthesized answer text.", "یک کنسول اپراتوری در محدوده tenant برای Decision Logهای Production و ترکیب کنترل‌شده پرسش‌وپاسخ پرونده. این محیط فقط شناسه‌ها، hashها و معیارهای عملیاتی را نمایش می‌دهد و هرگز پرامپت خام، سؤال، متن شواهد، پاسخ ارائه‌دهنده یا متن پاسخ ترکیب‌شده را افشا نمی‌کند.")}</p>
    </section>

    {(message || error) && <div dir="auto" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      {[
        [L("Events", "رویدادها"), metrics?.event_count ?? 0], [L("Needs attention", "نیازمند توجه"), metrics?.requires_attention_count ?? 0],
        [L("Pending reviews", "بازبینی‌های در انتظار"), metrics?.pending_human_review_count ?? 0], [L("Blocked / fallback", "مسدود / مسیر جایگزین"), metrics?.blocked_or_fallback_count ?? 0],
        [L("Grounding failures", "خطاهای استناد به منبع"), metrics?.verification_failure_count ?? 0], [L("P95 latency", "تأخیر P95"), metrics?.p95_latency_ms ? `${metrics.p95_latency_ms} ms` : "—"],
      ].map(([k, v]) => <div key={String(k)} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{k}</p><p className="mt-2 text-2xl font-semibold" dir={String(k).includes("P95") ? "ltr" : undefined}>{v}</p></div>)}
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-slate-600">{L("Workflow", "جریان کار")}<select value={workflow} onChange={(e) => setWorkflow(e.target.value as "" | Workflow)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="">{L("All", "همه")}</option><option value="document_processing">{aiLabel(locale, "document_processing")}</option><option value="claim_qa_synthesis">{aiLabel(locale, "claim_qa_synthesis")}</option></select></label>
        <label className="text-xs font-semibold text-slate-600">{L("Status", "وضعیت")}<input dir="ltr" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="completed / blocked" className="mt-1 block rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label>
        <label className="text-xs font-semibold text-slate-600">{L("Claim ID", "شناسه پرونده")}<input dir="ltr" value={claimId} onChange={(e) => setClaimId(e.target.value)} placeholder="UUID" className="mt-1 block w-72 rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm"><input type="checkbox" checked={attentionOnly} onChange={(e) => setAttentionOnly(e.target.checked)} /> {L("Requires attention only", "فقط موارد نیازمند توجه")}</label>
        <div className="ms-auto flex gap-2"><button disabled={busy !== null} onClick={() => void exportData("csv")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">{L("Export CSV", "خروجی CSV")}</button><button disabled={busy !== null} onClick={() => void exportData("json")} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">{L("Export JSON", "خروجی JSON")}</button></div>
      </div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold">{L("Unified operational events", "رویدادهای عملیاتی یکپارچه")}</h2><p className="mt-1 text-xs text-slate-500">{L(`${events?.total ?? 0} matching events · deterministic newest-first ordering`, `${events?.total ?? 0} رویداد منطبق · ترتیب قطعی از جدید به قدیم`)}</p></div>
      <div className="overflow-x-auto"><table className="min-w-full text-start text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">{L("Time", "زمان")}</th><th className="px-4 py-3">{L("Workflow", "جریان کار")}</th><th className="px-4 py-3">{L("Status", "وضعیت")}</th><th className="px-4 py-3">{L("Claim", "پرونده")}</th><th className="px-4 py-3">{L("Model", "مدل")}</th><th className="px-4 py-3">{L("Review", "بازبینی")}</th><th className="px-4 py-3">{L("Attention", "توجه")}</th></tr></thead><tbody>{events?.events.map((event) => <tr key={`${event.workflow_type}-${event.id}`} onClick={() => { setSelected(event); setReview((r) => ({ ...r, latency_ms: event.latency_ms ?? 1, observed_provider_cost_microusd: event.observed_provider_cost_microusd ?? 0, evidence_reference: `artifact://ai-operations/review/${event.id}` })); }} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"><td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500" dir="ltr">{formatDateTime(event.event_time, locale)}</td><td className="px-4 py-3 font-medium">{aiLabel(locale, event.workflow_type)}</td><td className="px-4 py-3">{aiLabel(locale, event.status)}{event.failure_code && <div className="mt-1 text-xs text-rose-600" dir="auto">{aiLabel(locale, event.failure_code)}</div>}</td><td className="px-4 py-3 font-mono text-xs" dir="ltr">{event.claim_id.slice(0, 8)}…</td><td className="px-4 py-3" dir="ltr">{event.model ?? "—"}</td><td className="px-4 py-3">{aiLabel(locale, event.human_review_state)}{event.human_review_action && ` · ${aiLabel(locale, event.human_review_action)}`}</td><td className="px-4 py-3">{event.requires_attention ? <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">{L("Review", "بازبینی")}</span> : <span className="text-emerald-700">{L("Clear", "بدون هشدار")}</span>}</td></tr>)}</tbody></table></div>
    </section>

    <section className="grid gap-5 xl:grid-cols-2">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><div><h2 className="font-semibold">{L("Different-human review queue", "صف بازبینی توسط فرد متفاوت")}</h2><p className="mt-1 text-xs text-slate-500">{L("Production Decision Log only; synthesis runs remain observability-only.", "فقط برای Production Decision Log؛ اجرای synthesis صرفاً مشاهده‌پذیر باقی می‌ماند.")}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{queue?.total ?? 0} {L("pending", "در انتظار")}</span></div><div className="mt-4 space-y-2">{queue?.events.slice(0, 8).map((event) => <button key={event.id} onClick={() => setSelected(event)} className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-3 text-start text-sm hover:bg-slate-50"><span><span className="font-medium">{aiLabel(locale, event.document_type)}</span><span className="ms-2 font-mono text-xs text-slate-500" dir="ltr">{event.claim_id.slice(0, 8)}…</span></span><span className="text-xs text-amber-700">{aiLabel(locale, "pending")}</span></button>)}</div></div>
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-semibold">{L("Operational quality", "کیفیت عملیاتی")}</h2><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div className="rounded-lg bg-slate-50 p-3">{L("Approve", "تأیید")} <strong className="float-end">{metrics?.approve_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">{L("Edit", "ویرایش")} <strong className="float-end">{metrics?.edit_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">{L("Reject", "رد")} <strong className="float-end">{metrics?.reject_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">{L("Unsupported", "بدون پشتوانه")} <strong className="float-end">{metrics?.unsupported_output_count ?? 0}</strong></div><div className="rounded-lg bg-slate-50 p-3">{L("Grounding", "استناد") } <strong className="float-end" dir="ltr">{metrics?.source_grounding_validity_bps == null ? "—" : `${(metrics.source_grounding_validity_bps / 100).toFixed(2)}%`}</strong></div><div className="rounded-lg bg-slate-50 p-3">{L("Tokens", "توکن‌ها")} <strong className="float-end">{metrics?.total_tokens ?? 0}</strong></div></div></div>
    </section>

    {selected && <section className="rounded-2xl border border-cyan-200 bg-white p-6 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase text-cyan-700">{L("Lineage drill-down", "جزئیات زنجیره ردیابی")}</p><h2 className="mt-1 text-xl font-semibold">{aiLabel(locale, selected.workflow_type)} · {aiLabel(locale, selected.status)}</h2></div><div className="flex gap-2"><Link href={`/claims/${selected.claim_id}`} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold">{L("Open claim workspace", "باز کردن فضای پرونده")}</Link><button onClick={() => setSelected(null)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">{L("Close", "بستن")}</button></div></div>
      <div className="mt-5 grid gap-3 text-xs md:grid-cols-2 xl:grid-cols-4"><div><span className="font-semibold text-slate-500">{L("Authorization", "مجوز")}</span><p className="mt-1 break-all font-mono" dir="ltr">{selected.authorization_id ?? "—"}</p></div><div><span className="font-semibold text-slate-500">{L("Authorization hash", "Hash مجوز")}</span><p className="mt-1 font-mono" dir="ltr">{hash(selected.authorization_hash)}</p></div><div><span className="font-semibold text-slate-500">{L("Policy hash", "Hash policy")}</span><p className="mt-1 font-mono" dir="ltr">{hash(selected.eligibility_policy_hash)}</p></div><div><span className="font-semibold text-slate-500">{L("Result / run hash", "Hash نتیجه / اجرا")}</span><p className="mt-1 font-mono" dir="ltr">{hash(selected.run_hash ?? selected.result_set_hash)}</p></div><div><span className="font-semibold text-slate-500">{L("Input hash", "Hash ورودی")}</span><p className="mt-1 font-mono" dir="ltr">{hash(selected.input_hash)}</p></div><div><span className="font-semibold text-slate-500">{L("Output hash", "Hash خروجی")}</span><p className="mt-1 font-mono" dir="ltr">{hash(selected.output_hash)}</p></div><div><span className="font-semibold text-slate-500">{L("Answer / review hash", "Hash پاسخ / بازبینی")}</span><p className="mt-1 font-mono" dir="ltr">{hash(selected.answer_hash ?? selected.review_hash)}</p></div><div><span className="font-semibold text-slate-500">{L("Bundle", "بسته")}</span><p className="mt-1" dir="ltr">{selected.prompt_bundle_version ?? "—"} · {selected.schema_bundle_version ?? "—"}</p></div></div>
      {selected.attention_reasons.length > 0 && <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" dir="auto">{L("Attention:", "توجه:")} {selected.attention_reasons.join(" · ")}</div>}

      {selected.workflow_type === "document_processing" && selected.human_review_state === "pending" && <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="font-semibold">{L("Complete existing different-human review", "تکمیل بازبینی موجود توسط فرد متفاوت")}</h3><p className="mt-1 text-xs text-slate-500">{L("Use the controlled claim/document workspace to verify these metrics before submitting. Requesters cannot review their own run.", "پیش از ثبت، این معیارها را در فضای کنترل‌شده پرونده/سند بررسی کنید. درخواست‌کننده نمی‌تواند اجرای خودش را بازبینی کند.")}</p><div className="mt-3 grid gap-3 md:grid-cols-4">{(["output_candidate_count","human_edit_count","unsupported_output_count","source_grounded_output_count","source_grounding_total_count","latency_ms","observed_provider_cost_microusd"] as const).map((field) => <label key={field} className="text-xs font-semibold text-slate-600">{aiLabel(locale, field)}<input dir="ltr" type="number" min={0} value={review[field]} onChange={(e) => setReview({ ...review, [field]: Number(e.target.value) })} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal" /></label>)}</div><label className="mt-3 block text-xs font-semibold text-slate-600">{L("Evidence reference", "مرجع شواهد")}<input dir="ltr" value={review.evidence_reference} onChange={(e) => setReview({ ...review, evidence_reference: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><label className="mt-3 block text-xs font-semibold text-slate-600">{L("Review note", "یادداشت بازبینی")}<textarea dir="auto" value={review.note} onChange={(e) => setReview({ ...review, note: e.target.value })} className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><div className="mt-3 flex gap-2">{(["approve","edit","reject"] as const).map((action) => <button key={action} disabled={busy !== null} onClick={() => void reviewEvent(action)} className={`rounded-lg px-4 py-2 text-sm font-semibold ${action === "approve" ? "bg-emerald-700 text-white" : action === "reject" ? "border border-rose-300 text-rose-700" : "border border-amber-300 text-amber-800"}`}>{aiLabel(locale, action)}</button>)}</div></div>}

      {selected.authorization_id && <div className="mt-6 border-t border-slate-200 pt-5"><h3 className="font-semibold">{L("Explicit incident handoff", "تحویل صریح incident")}</h3><p className="mt-1 text-xs text-slate-500">{L("This does not autonomously declare an incident. Submitting below is an explicit human action that reuses the existing Production-wide incident service.", "این بخش به‌طور خودکار incident اعلام نمی‌کند. ثبت فرم زیر یک اقدام صریح انسانی است که سرویس incident موجود در سطح Production را استفاده می‌کند.")}</p><div className="mt-3 grid gap-3 md:grid-cols-2"><label className="text-xs font-semibold text-slate-600">{L("Severity", "شدت")}<select value={incident.severity} onChange={(e) => setIncident({ ...incident, severity: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="low">{aiLabel(locale, "low")}</option><option value="medium">{aiLabel(locale, "medium")}</option><option value="high">{aiLabel(locale, "high")}</option><option value="critical">{aiLabel(locale, "critical")}</option></select></label><label className="text-xs font-semibold text-slate-600">{L("Category", "دسته") }<select value={incident.category} onChange={(e) => setIncident({ ...incident, category: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal"><option value="quality">{aiLabel(locale, "quality")}</option><option value="cost">{aiLabel(locale, "cost")}</option><option value="availability">{aiLabel(locale, "availability")}</option><option value="reliability">{aiLabel(locale, "reliability")}</option><option value="privacy">{aiLabel(locale, "privacy")}</option><option value="security">{aiLabel(locale, "security")}</option><option value="cross_tenant">{aiLabel(locale, "cross_tenant")}</option><option value="other">{aiLabel(locale, "other")}</option></select></label></div><label className="mt-3 block text-xs font-semibold text-slate-600">{L("Evidence reference", "مرجع شواهد")}<input dir="ltr" value={incident.evidence_reference} onChange={(e) => setIncident({ ...incident, evidence_reference: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><label className="mt-3 block text-xs font-semibold text-slate-600">{L("Incident note", "یادداشت incident")}<textarea dir="auto" value={incident.note} onChange={(e) => setIncident({ ...incident, note: e.target.value })} className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label><button disabled={busy !== null} onClick={() => void handoffIncident()} className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">{L("Hand off to incident workflow", "تحویل به جریان incident")}</button></div>}
    </section>}

    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><strong>{L("Content-free governance boundary:", "مرز حاکمیتی بدون محتوای خام:")}</strong> {L("AI Operations does not create AI authorization, widen provider/model/document permissions, expose raw claim/model content, persist transient Q&A wording, change ClaimFact, or make coverage, liability, causation, recoverability, reserve, settlement or payment decisions.", "AI Operations مجوز AI ایجاد نمی‌کند، دسترسی ارائه‌دهنده/مدل/سند را گسترش نمی‌دهد، محتوای خام پرونده یا مدل را افشا نمی‌کند، متن موقت Q&A را نگه نمی‌دارد، ClaimFact را تغییر نمی‌دهد و درباره پوشش، مسئولیت، سببیت، قابلیت بازیافت، ذخیره، سازش یا پرداخت تصمیم نمی‌گیرد.")}</section>
  </div>;
}
