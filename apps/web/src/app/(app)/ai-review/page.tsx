"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import {
  ApiError,
  bulkApproveAIExtractions,
  getAIReviewDetail,
  getAISourcePreview,
  listAIReview,
  listAIReviewGroups,
  reviewAIExtraction,
  reviewAIGroup,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { aiLabel, aiT } from "@/lib/i18n-ai-operator";
import type { Locale } from "@/lib/i18n";
import type { AIReviewDetail, AIReviewGroup, AIReviewItem, AIReviewStatus, AISemanticKind, AISourcePreview } from "@/lib/types";

function humanField(path: string) {
  return path
    .replace(/\[(\d+)\]/g, " $1")
    .split(".")
    .map((part) => part.replaceAll("_", " "))
    .join(" · ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayValue(value: unknown, locale: Locale) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return aiT(locale, value ? "Yes" : "No", value ? "بله" : "خیر");
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

function reviewGroupStateKey(group: AIReviewGroup) { return `${group.document_id}:${group.group_key}`; }

export default function AIReviewPage() {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => aiT(locale, en, fa);
  const [claimId, setClaimId] = useState("");
  const [queryReady, setQueryReady] = useState(false);
  const [items, setItems] = useState<AIReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [groups, setGroups] = useState<AIReviewGroup[]>([]);
  const [attentionGroups, setAttentionGroups] = useState(0);
  const [viewMode, setViewMode] = useState<"groups" | "fields">("groups");
  const [attentionOnly, setAttentionOnly] = useState(true);
  const [groupReasons, setGroupReasons] = useState<Record<string, string>>({});
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
      const groupParams = new URLSearchParams();
      groupParams.set("review_status", statusFilter);
      groupParams.set("limit_groups", "200");
      groupParams.set("attention_only", attentionOnly ? "true" : "false");
      if (claimId) groupParams.set("claim_id", claimId);
      const [response, grouped] = await Promise.all([listAIReview(params), listAIReviewGroups(groupParams)]);
      setItems(response.items);
      setTotal(response.total);
      setGroups(grouped.groups);
      setAttentionGroups(grouped.attention_groups);
      setSelected((current) => current.filter((id) => response.items.some((item) => item.extraction_id === id && item.bulk_approvable)));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : L("AI review queue could not be loaded.", "صف بازبینی AI بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setClaimId(new URLSearchParams(window.location.search).get("claim_id") ?? "");
    setQueryReady(true);
  }, []);

  useEffect(() => { if (queryReady) void load(); }, [statusFilter, semanticFilter, claimId, attentionOnly, queryReady]);

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
      setError(err instanceof ApiError ? err.detail : L("Review action could not be saved.", "عملیات بازبینی ذخیره نشد."));
    } finally {
      setWorking(false);
    }
  }

  async function toggleSource(item: AIReviewItem) {
    if (sourceOpen === item.extraction_id) { setSourceOpen(null); return; }
    setSourceOpen(item.extraction_id);
    if (!source[item.extraction_id]) {
      try {
        const preview = await getAISourcePreview(item.extraction_id);
        setSource((current) => ({ ...current, [item.extraction_id]: preview }));
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : L("Source preview could not be loaded.", "پیش‌نمایش منبع بارگذاری نشد."));
      }
    }
  }

  async function toggleHistory(item: AIReviewItem) {
    if (historyOpen === item.extraction_id) { setHistoryOpen(null); return; }
    setHistoryOpen(item.extraction_id);
    if (!history[item.extraction_id]) {
      try {
        const detail = await getAIReviewDetail(item.extraction_id);
        setHistory((current) => ({ ...current, [item.extraction_id]: detail }));
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : L("Review history could not be loaded.", "سابقه بازبینی بارگذاری نشد."));
      }
    }
  }

  async function reviewGroup(group: AIReviewGroup, action: "approve" | "reject") {
    const ids = group.items.filter((item) => item.human_status === "pending").map((item) => item.extraction_id);
    if (!ids.length) return;
    setWorking(true);
    setError("");
    try {
      const stateKey = reviewGroupStateKey(group);
      await reviewAIGroup(ids, action, groupReasons[stateKey]?.trim() || undefined);
      setGroupReasons((current) => { const next = { ...current }; delete next[stateKey]; return next; });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : L("Grouped review could not be completed.", "بازبینی گروهی تکمیل نشد."));
    } finally {
      setWorking(false);
    }
  }

  async function bulkApprove() {
    if (!selected.length) return;
    setWorking(true);
    setError("");
    try {
      // Audit content stays locale-neutral; changing the UI language must not rewrite persisted review notes.
      await bulkApproveAIExtractions(selected, "Bulk-approved after source-linked metadata review.");
      setSelected([]);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : L("Bulk approval could not be completed.", "تأیید گروهی تکمیل نشد."));
    } finally {
      setWorking(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <p className="eyebrow">{L("Human-in-the-loop", "انسان در حلقه تصمیم")}</p>
          <h1 className="page-title">{L("AI Review", "بازبینی AI")}</h1>
          <p className="page-subtitle">{L(
            "Exception-first review groups related evidence into rows and line items. Resolve judgment-heavy groups first; only explicit human actions can promote facts into the authoritative claim-facts layer.",
            "بازبینی استثنامحور، شواهد مرتبط را در ردیف‌ها و اقلام گروه‌بندی می‌کند. ابتدا موارد نیازمند قضاوت را بررسی کنید؛ فقط اقدام صریح انسانی می‌تواند واقعیت‌ها را وارد لایه معتبر Claim Facts کند.",
          )}</p>
        </div>
        {selected.length ? <button disabled={working} onClick={bulkApprove} className="primary-button">{L(`Approve selected (${selected.length})`, `تأیید موارد انتخاب‌شده (${selected.length})`)}</button> : null}
      </div>

      {claimId ? <div className="mt-5 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-900">{L("Filtered to one claim.", "فقط یک پرونده نمایش داده می‌شود.")} <Link href="/ai-review" className="font-semibold underline">{L("Show organization queue", "نمایش صف سازمان")}</Link></div> : null}
      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">{error}</div> : null}

      <section className="panel mt-6 p-4">
        <div className="grid gap-3 md:grid-cols-[180px_200px_200px_1fr_auto] md:items-end">
          <label><span className="label">{L("Review view", "نمای بازبینی")}</span><select className="field" value={viewMode} onChange={(e) => setViewMode(e.target.value as "groups" | "fields")}><option value="groups">{L("Grouped / rows", "گروهی / ردیفی")}</option><option value="fields">{L("Field-by-field", "فیلد به فیلد")}</option></select></label>
          <label><span className="label">{L("Review status", "وضعیت بازبینی")}</span><select className="field" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as AIReviewStatus | "all")}><option value="pending">{aiLabel(locale, "pending")}</option><option value="approved">{aiLabel(locale, "approved")}</option><option value="edited">{aiLabel(locale, "edited")}</option><option value="rejected">{aiLabel(locale, "rejected")}</option><option value="all">{aiLabel(locale, "all")}</option></select></label>
          <label><span className="label">{L("Evidence type", "نوع شواهد")}</span><select disabled={viewMode === "groups"} className="field disabled:opacity-50" value={semanticFilter} onChange={(e) => setSemanticFilter(e.target.value as AISemanticKind | "all")}><option value="all">{aiLabel(locale, "all")}</option><option value="fact">{aiLabel(locale, "fact")}</option><option value="opinion">{aiLabel(locale, "opinion")}</option><option value="inference">{aiLabel(locale, "inference")}</option></select></label>
          <div className="text-sm text-slate-500">{loading ? L("Loading review queue…", "در حال بارگذاری صف بازبینی…") : viewMode === "groups" ? L(`${groups.length} review group${groups.length === 1 ? "" : "s"} · ${attentionGroups} need attention`, `${groups.length} گروه بازبینی · ${attentionGroups} نیازمند توجه`) : L(`${total} extraction candidate${total === 1 ? "" : "s"}`, `${total} کاندید استخراج`)}</div>
          {viewMode === "fields" && bulkEligible.length ? <button className="secondary-button" onClick={() => setSelected(selected.length === bulkEligible.length ? [] : bulkEligible.map((item) => item.extraction_id))}>{selected.length === bulkEligible.length ? L("Clear selection", "پاک کردن انتخاب") : L("Select eligible", "انتخاب واجد شرایط‌ها")}</button> : null}
        </div>
        {viewMode === "groups" ? <label className="mt-3 inline-flex items-center gap-2 text-xs font-semibold text-slate-600"><input type="checkbox" checked={attentionOnly} onChange={(e) => setAttentionOnly(e.target.checked)} />{L("Show only groups that need judgment", "فقط گروه‌های نیازمند قضاوت نمایش داده شوند")}</label> : null}
      </section>

      {viewMode === "groups" ? <div className="mt-5 space-y-4">
        {!loading && groups.length === 0 ? <div className="panel py-16 text-center"><p className="text-sm font-semibold text-slate-800">{L("No grouped review items in this view.", "در این نما مورد گروهی برای بازبینی وجود ندارد.")}</p></div> : null}
        {groups.map((group) => <article key={`${group.document_id}-${group.group_key}`} className={`panel overflow-hidden ${group.needs_attention ? "ring-1 ring-amber-200" : ""}`}>
          <div className="flex flex-col justify-between gap-4 border-b border-slate-200 p-5 lg:flex-row lg:items-start">
            <div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-1 text-[11px] font-bold uppercase ${group.needs_attention ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>{aiLabel(locale, group.needs_attention ? "needs_attention" : "routine")}</span><span className="text-xs text-slate-400">{L(`${Math.round(Number(group.min_confidence) * 100)}% minimum confidence`, `حداقل اطمینان ${Math.round(Number(group.min_confidence) * 100)}٪`)}</span></div><h2 className="mt-2 text-base font-semibold text-slate-950" dir="auto">{group.label}</h2><p className="mt-1 text-xs text-slate-500" dir="auto">{group.document_name} · <span dir="ltr">{group.claim_reference}</span> · {group.vessel_name}</p>{group.attention_reasons.length ? <p className="mt-2 text-xs font-medium text-amber-700" dir="auto">{group.attention_reasons.join(" · ")}</p> : null}</div>
            <div className="flex flex-wrap gap-2"><Link href={`/claims/${group.claim_id}`} className="secondary-button px-3 py-2 text-xs">{L("Open claim", "باز کردن پرونده")}</Link>{group.pending_count ? <><button disabled={working} onClick={() => reviewGroup(group, "approve")} className="primary-button px-3 py-2 text-xs">{L(`Approve group (${group.pending_count})`, `تأیید گروه (${group.pending_count})`)}</button><button disabled={working} onClick={() => reviewGroup(group, "reject")} className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-50">{L("Reject group", "رد گروه")}</button></> : null}</div>
          </div>
          <div className="overflow-x-auto"><table className="min-w-full text-start text-xs"><thead className="bg-slate-50 text-slate-500"><tr><th className="px-4 py-2 font-semibold">{L("Field", "فیلد")}</th><th className="px-4 py-2 font-semibold">{L("AI value", "مقدار AI")}</th><th className="px-4 py-2 font-semibold">{L("Type", "نوع")}</th><th className="px-4 py-2 font-semibold">{L("Confidence", "اطمینان")}</th><th className="px-4 py-2 font-semibold">{L("Evidence", "شواهد")}</th></tr></thead><tbody className="divide-y divide-slate-100">{group.items.map((item) => <tr key={item.extraction_id}><td className="px-4 py-3 font-semibold text-slate-800" dir="ltr">{humanField(item.field_path.replace(`${group.group_key}.`, ""))}</td><td className="px-4 py-3 text-slate-700" dir="auto">{displayValue(item.normalized_value ?? item.ai_value, locale)}</td><td className="px-4 py-3"><span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${semanticTone[item.semantic_kind]}`}>{aiLabel(locale, item.semantic_kind)}</span></td><td className="px-4 py-3 text-slate-500" dir="ltr">{Math.round(Number(item.confidence) * 100)}%</td><td className="max-w-sm px-4 py-3 text-slate-500" dir="auto">{item.source_quote || L("No source quote", "نقل‌قول منبع موجود نیست")}{!item.source_verified ? <span className="ms-2 font-semibold text-amber-700">{L("Verify manually", "بررسی دستی")}</span> : null}</td></tr>)}</tbody></table></div>
          {group.pending_count ? <div className="border-t border-slate-200 bg-slate-50 p-4"><label><span className="label">{L("Group review note", "یادداشت بازبینی گروه")} {group.requires_reason ? L("(required)", "(الزامی)") : L("(optional)", "(اختیاری)")}</span><input dir="auto" className="field" value={groupReasons[reviewGroupStateKey(group)] ?? ""} onChange={(e) => setGroupReasons((current) => ({ ...current, [reviewGroupStateKey(group)]: e.target.value }))} placeholder={group.requires_reason ? L("Record how the unverified source was manually checked.", "نحوه بررسی دستی منبع تأییدنشده را ثبت کنید.") : L("Optional note for this row/group.", "یادداشت اختیاری برای این ردیف/گروه.")} /></label></div> : null}
        </article>)}
      </div> : <div className="mt-5 space-y-4">
        {!loading && items.length === 0 ? <div className="panel py-16 text-center"><p className="text-sm font-semibold text-slate-800">{L("No extraction candidates in this view.", "در این نما کاندید استخراجی وجود ندارد.")}</p><p className="mt-2 text-sm text-slate-500">{L("AI-generated values appear here only after document intelligence has completed.", "مقادیر تولیدشده توسط AI فقط پس از تکمیل هوشمندی اسناد در اینجا ظاهر می‌شوند.")}</p></div> : null}
        {items.map((item) => {
          const currentSource = source[item.extraction_id];
          const isEditing = editing === item.extraction_id;
          const checked = selected.includes(item.extraction_id);
          return (
            <article key={item.extraction_id} className="panel overflow-hidden">
              <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(260px,0.9fr)_auto]">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    {item.bulk_approvable ? <input aria-label={L("Select for bulk approval", "انتخاب برای تأیید گروهی")} type="checkbox" checked={checked} onChange={() => setSelected((current) => current.includes(item.extraction_id) ? current.filter((id) => id !== item.extraction_id) : [...current, item.extraction_id])} className="h-4 w-4" /> : null}
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${semanticTone[item.semantic_kind]}`}>{aiLabel(locale, item.semantic_kind)}</span>
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${reviewTone[item.human_status]}`}>{aiLabel(locale, item.human_status)}</span>
                    <span className="text-xs font-medium text-slate-400" dir="ltr">{Math.round(Number(item.confidence) * 100)}% {L("confidence", "")}</span>
                  </div>
                  <h2 className="mt-3 text-base font-semibold text-slate-950" dir="ltr">{humanField(item.field_path)}</h2>
                  <p className="mt-1 text-xs text-slate-400" dir="ltr">{item.field_path}</p>
                  <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">{L("AI candidate", "کاندید AI")}</p><p className="mt-2 break-words text-sm font-semibold text-slate-900" dir="auto">{displayValue(item.normalized_value ?? item.ai_value, locale)}</p></div>
                  {item.human_status !== "pending" ? <div className="mt-3 text-xs text-slate-500">{L("Human-approved value:", "مقدار تأییدشده توسط انسان:")} <span className="font-semibold text-slate-700" dir="auto">{displayValue(item.approved_value, locale)}</span></div> : null}
                </div>

                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">{L("Evidence source", "منبع شواهد")}</p>
                  <p className="mt-2 text-sm leading-6 text-slate-700" dir="auto">{item.source_quote ? `“${item.source_quote}”` : L("No source quote supplied.", "نقل‌قول منبع ارائه نشده است.")}</p>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500"><span dir="auto">{item.document_name}</span><span dir="ltr">{item.source_locator_type && item.source_locator_value ? `${item.source_locator_type}: ${item.source_locator_value}` : L("Locator unavailable", "مکان‌یاب موجود نیست")}</span><span className={item.source_verified ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>{item.source_verified ? L("Source verified", "منبع تأیید شده") : L("Manual source check required", "بررسی دستی منبع الزامی است")}</span></div>
                  {item.validation_warnings?.length ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800" dir="auto">{item.validation_warnings.join(" ")}</div> : null}
                  {!item.source_verified && item.human_status === "pending" ? <label className="mt-3 block"><span className="label">{L("Manual verification reason", "دلیل بررسی دستی")}</span><textarea dir="auto" className="field resize-y" rows={2} value={reviewReasons[item.extraction_id] ?? ""} onChange={(e) => setReviewReasons((current) => ({ ...current, [item.extraction_id]: e.target.value }))} placeholder={L("Required before approving or editing an unverified source citation.", "پیش از تأیید یا ویرایش استناد منبع تأییدنشده الزامی است.")} /></label> : null}
                  <div className="mt-3 flex flex-wrap gap-4"><button onClick={() => toggleSource(item)} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">{sourceOpen === item.extraction_id ? L("Hide source context", "پنهان کردن متن منبع") : L("View source context", "مشاهده متن منبع")}</button><button onClick={() => toggleHistory(item)} className="text-xs font-semibold text-slate-600 hover:text-slate-900">{historyOpen === item.extraction_id ? L("Hide review history", "پنهان کردن سابقه بازبینی") : L("Review history", "سابقه بازبینی")}</button></div>
                </div>

                <div className="flex min-w-[170px] flex-col gap-2 lg:items-stretch">
                  <Link href={`/claims/${item.claim_id}`} className="text-sm font-semibold text-slate-900 hover:text-cyan-800" dir="ltr">{item.claim_reference}</Link>
                  <span className="text-xs text-slate-500" dir="auto">{item.vessel_name}</span>
                  {item.human_status === "pending" ? <div className="mt-2 grid gap-2"><button disabled={working} onClick={() => review(item, "approve")} className="secondary-button justify-center">{L("Approve", "تأیید")}</button><button disabled={working} onClick={() => { setEditing(item.extraction_id); setEditText(editValue(item.normalized_value ?? item.ai_value)); }} className="secondary-button justify-center">{L("Edit", "ویرایش")}</button><button disabled={working} onClick={() => review(item, "reject")} className="rounded-lg border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-red-700 hover:bg-red-50">{L("Reject", "رد")}</button></div> : null}
                </div>
              </div>

              {sourceOpen === item.extraction_id ? <div className="border-t border-slate-200 bg-slate-50 px-5 py-4"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">{L("Source segment", "بخش منبع")}</p>{currentSource ? <pre dir="auto" className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-4 font-sans text-xs leading-6 text-slate-700">{currentSource.segment_text ?? L("Source segment is unavailable.", "بخش منبع موجود نیست.")}</pre> : <p className="mt-3 text-sm text-slate-500">{L("Loading source context…", "در حال بارگذاری متن منبع…")}</p>}</div> : null}

              {historyOpen === item.extraction_id ? <div className="border-t border-slate-200 bg-white px-5 py-4"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">{L("Human review history", "سابقه بازبینی انسانی")}</p>{history[item.extraction_id] ? <div className="mt-3 space-y-3">{history[item.extraction_id]!.feedback.length ? history[item.extraction_id]!.feedback.map((entry) => <div key={entry.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-semibold uppercase tracking-wide text-slate-700">{aiLabel(locale, entry.action)}</span><span className="text-xs text-slate-400" dir="ltr">{formatDateTime(entry.created_at, locale)}</span></div><p className="mt-2 text-sm text-slate-700" dir="auto">{entry.reviewer_name ?? entry.reviewer_email ?? L("Reviewer unavailable", "بازبین مشخص نیست")}</p><p className="mt-1 text-xs text-slate-500" dir="auto">{L("Human value:", "مقدار انسانی:")} {displayValue(entry.human_value, locale)}</p>{entry.reason ? <p className="mt-2 text-xs leading-5 text-slate-600" dir="auto">{L("Reason:", "دلیل:")} {entry.reason}</p> : null}</div>) : <p className="text-sm text-slate-500">{L("No human review actions recorded yet.", "هنوز اقدام بازبینی انسانی ثبت نشده است.")}</p>}{history[item.extraction_id]!.current_claim_fact ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">{L("Current approved claim fact", "واقعیت فعلی تأییدشده پرونده")} · {L("version", "نسخه")} <span dir="ltr">{history[item.extraction_id]!.current_claim_fact!.version}</span></div> : null}</div> : <p className="mt-3 text-sm text-slate-500">{L("Loading review history…", "در حال بارگذاری سابقه بازبینی…")}</p>}</div> : null}

              {isEditing ? <div className="border-t border-slate-200 bg-white px-5 py-5"><div className="grid gap-4 lg:grid-cols-[1fr_1fr_auto]"><label><span className="label">{L("Corrected value", "مقدار اصلاح‌شده")}</span><textarea dir="auto" className="field min-h-24 resize-y" value={editText} onChange={(e) => setEditText(e.target.value)} /></label><label><span className="label">{L("Review reason", "دلیل بازبینی")}</span><textarea dir="auto" className="field min-h-24 resize-y" value={reviewReasons[item.extraction_id] ?? ""} onChange={(e) => setReviewReasons((current) => ({ ...current, [item.extraction_id]: e.target.value }))} placeholder={L("Optional for verified sources; required if the source citation is unverified.", "برای منابع تأییدشده اختیاری است؛ اگر استناد منبع تأیید نشده باشد الزامی است.")} /></label><div className="flex items-end gap-2"><button disabled={working} onClick={() => review(item, "edit")} className="primary-button">{L("Save correction", "ذخیره اصلاح")}</button><button disabled={working} onClick={() => setEditing(null)} className="secondary-button">{L("Cancel", "لغو")}</button></div></div></div> : null}
            </article>
          );
        })}
      </div>}
    </div>
  );
}
