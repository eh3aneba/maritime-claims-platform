"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, getFinancialReview, resolveFinancialFlag, updateCostStatus } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import type { CostReviewStatus, FinancialCostItem, FinancialReviewResponse } from "@/lib/types";

const statusLabels: Record<CostReviewStatus, string> = {
  claimed: "Claimed",
  under_review: "Under review",
  potentially_recoverable: "Potentially recoverable",
  potentially_non_recoverable: "Potentially non-recoverable",
  accepted: "Accepted",
  rejected: "Rejected",
  paid: "Paid",
};

function sumItems(items: FinancialCostItem[], statuses?: CostReviewStatus[]) {
  const totals: Record<string, number> = {};
  for (const item of items) {
    if (statuses && !statuses.includes(item.review_status)) continue;
    totals[item.currency] = (totals[item.currency] ?? 0) + Number(item.amount);
  }
  return totals;
}

function totalsText(totals: Record<string, number>) {
  const entries = Object.entries(totals);
  if (!entries.length) return "None recorded";
  return entries.map(([currency, amount]) => formatMoney(amount, currency)).join(" · ");
}

export default function FinancialReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<FinancialReviewResponse | null>(null);
  const [error, setError] = useState("");

  const load = () => getFinancialReview(id).then((result) => { setData(result); setError(""); }).catch((e) => setError(e instanceof ApiError ? e.detail : "Financial review could not be loaded."));
  useEffect(() => { load(); }, [id]);

  async function setStatus(itemId: string, status: CostReviewStatus) {
    const reason = window.prompt("Reason for status change?");
    if (!reason) return;
    await updateCostStatus(id, itemId, status, reason);
    load();
  }

  async function resolve(idFlag: string) {
    const note = window.prompt("Resolution/explanation?");
    if (!note) return;
    await resolveFinancialFlag(id, idFlag, "explained", note);
    load();
  }

  const groups = useMemo(() => {
    if (!data) return [];
    const grouped = new Map<string, FinancialCostItem[]>();
    for (const item of data.items) grouped.set(item.document_id, [...(grouped.get(item.document_id) ?? []), item]);
    return Array.from(grouped.entries()).map(([documentId, items]) => ({ documentId, items })).sort((a, b) => {
      const ak = a.items[0]?.document_kind === "invoice" ? 0 : 1;
      const bk = b.items[0]?.document_kind === "invoice" ? 0 : 1;
      return ak - bk;
    });
  }, [data]);

  if (!data) return <div className="panel p-6">{error || "Loading financial review…"}</div>;

  const invoiceTotals = Object.fromEntries(Object.entries(data.totals_by_currency).map(([currency, value]) => [currency, Number(value)]));
  const acceptedTotals = sumItems(data.items.filter((item) => item.document_kind === "invoice"), ["accepted", "paid"]);
  const paidTotals = sumItems(data.items.filter((item) => item.document_kind === "invoice"), ["paid"]);
  const latestReserve = data.reserve_history[0];

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500">← Back to claim</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-end"><div><p className="eyebrow">Cost control intelligence</p><h1 className="mt-2 text-3xl font-semibold text-slate-950">Financial review</h1><p className="mt-2 text-sm text-slate-500">Human-reviewed commercial evidence, deterministic flags and reserve history. No automatic recoverability or supplier selection.</p></div><Link href={`/claims/${id}/adjustment`} className="primary-button whitespace-nowrap">Open Adjustment Workspace</Link></div>
    {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

    <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <div className="panel p-5"><p className="metric-label">Current reserve</p><p className="metric-value text-xl">{latestReserve ? formatMoney(latestReserve.amount, latestReserve.currency) : "None recorded"}</p></div>
      <div className="panel p-5"><p className="metric-label">Actual / invoiced</p><p className="metric-value text-xl">{totalsText(invoiceTotals)}</p></div>
      <div className="panel p-5"><p className="metric-label">Accepted invoice cost</p><p className="metric-value text-xl">{totalsText(acceptedTotals)}</p></div>
      <div className="panel p-5"><p className="metric-label">Paid</p><p className="metric-value text-xl">{totalsText(paidTotals)}</p></div>
      <div className="panel p-5"><p className="metric-label">Open review flags</p><p className="metric-value">{data.flags.filter((flag) => flag.status === "open").length}</p></div>
    </section>

    <section className="panel mt-6 p-6">
      <div className="flex flex-col justify-between gap-2 lg:flex-row lg:items-end"><div><h2 className="section-title">Commercial evidence & cost schedule</h2><p className="section-subtitle">Invoice costs and quotation alternatives are grouped by source document so alternative repair scopes are never presented as cumulative claim exposure.</p></div></div>
      <div className="mt-5 space-y-5">{groups.map(({ documentId, items }) => {
        const first = items[0];
        const isInvoice = first.document_kind === "invoice";
        const groupTotal = items.reduce((sum, item) => sum + Number(item.amount), 0);
        const quotation = data.quotations.find((q) => q.document_id === documentId);
        const label = isInvoice ? "Invoice / actual commercial evidence" : "Quotation alternative";
        return <div key={documentId} className="rounded-xl border border-slate-200">
          <div className="flex flex-col justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 md:flex-row md:items-center"><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 font-semibold text-slate-900">{first.supplier || (isInvoice ? "Invoice" : "Quotation")} {first.document_number || ""}</p>{!isInvoice && quotation?.scope_summary ? <p className="mt-1 text-xs text-slate-500">{quotation.scope_summary}</p> : null}</div><div className="text-left md:text-right"><p className="text-xs uppercase tracking-wide text-slate-400">Reviewed line-item total</p><p className="font-semibold text-slate-900">{formatMoney(groupTotal, first.currency)}</p>{!isInvoice && quotation?.total ? <p className="text-xs text-slate-500">Document total: {formatMoney(quotation.total, quotation.currency || first.currency)}</p> : null}</div></div>
          <div className="overflow-x-auto"><table className="data-table min-w-[900px]"><thead><tr><th>Description</th><th>Amount</th><th>Category</th><th>Evidence type</th><th>Status</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.description}</td><td>{formatMoney(item.amount, item.currency)}</td><td>{item.category || "—"}</td><td><span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{isInvoice ? "Actual / invoiced" : "Quoted alternative"}</span></td><td><select value={item.review_status} onChange={(e) => setStatus(item.id, e.target.value as CostReviewStatus)} className="field py-1 text-xs">{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td></tr>)}</tbody></table></div>
        </div>;
      })}</div>
    </section>

    <section className="mt-6 grid gap-6 xl:grid-cols-2">
      <div className="panel p-6"><h2 className="section-title">Financial flags</h2><p className="section-subtitle">Flags are review cues only. They do not determine recoverability or select a supplier.</p><div className="mt-4 space-y-3">{data.flags.length ? data.flags.map((flag) => <div key={flag.id} className="rounded-lg border border-slate-200 p-4"><div className="flex justify-between gap-3"><div><p className="font-semibold text-slate-900">{flag.title}</p><p className="mt-1 text-xs uppercase text-slate-400">Review severity: {flag.severity} · {flag.flag_type.replaceAll("_", " ")}</p></div><span className="text-xs font-semibold capitalize">{flag.status.replaceAll("_", " ")}</span></div><p className="mt-3 text-sm text-slate-600">{flag.explanation}</p>{flag.status === "open" ? <button onClick={() => resolve(flag.id)} className="secondary-button mt-3">Explain / resolve</button> : flag.resolution_note ? <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Review note: {flag.resolution_note}</p> : null}</div>) : <p className="text-sm text-slate-500">No current flags.</p>}</div></div>
      <div className="panel p-6"><h2 className="section-title">Quotation alternatives</h2><p className="section-subtitle">Different scopes are displayed as alternatives and are not added together as claim exposure.</p><div className="mt-4 space-y-3">{data.quotations.map((quote) => <div key={quote.document_id} className="rounded-lg border border-slate-200 p-4"><p className="font-semibold">{quote.supplier || "Quotation"} {quote.quotation_number || ""}</p><p className="mt-1 text-lg font-semibold text-slate-900">{quote.total ? formatMoney(quote.total, quote.currency || "USD") : "Total not established"}</p><p className="mt-2 text-sm text-slate-600">{quote.scope_summary || "Scope not yet approved."}</p><p className="mt-2 text-xs text-slate-400">Lead time: {quote.lead_time || "—"} · Repair duration: {quote.repair_duration || "—"}</p></div>)}</div></div>
    </section>

    <section className="panel mt-6 p-6"><h2 className="section-title">Reserve history</h2><div className="mt-4 space-y-2">{data.reserve_history.length ? data.reserve_history.map((row) => <div key={row.id} className="flex flex-col justify-between gap-2 border-b border-slate-100 py-3 sm:flex-row"><div><p className="font-medium">{formatMoney(row.amount, row.currency)}</p><p className="text-xs text-slate-500">{row.reason}</p></div><span className="text-xs text-slate-400">{formatDateTime(row.created_at)}</span></div>) : <p className="text-sm text-slate-500">No reserve history recorded.</p>}</div></section>
  </div>;
}
