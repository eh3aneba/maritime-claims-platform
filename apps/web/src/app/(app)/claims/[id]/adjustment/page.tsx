"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createAdjustmentStatement,
  getClaim,
  getCurrentUser,
  getFinancialReview,
  listAdjustmentStatements,
  reviewAdjustmentStatement,
  submitAdjustmentStatement,
  updateAdjustmentLine,
  updateAdjustmentStatement,
} from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type {
  AdjustmentBasis,
  AdjustmentLine,
  AdjustmentStatement,
  AdjustmentTreatment,
  Claim,
  CurrentUser,
  FinancialReviewResponse,
} from "@/lib/types";

const treatmentLabels: Record<AdjustmentTreatment, string> = {
  pending: "Pending decision",
  included: "Included",
  excluded: "Excluded",
  apportioned: "Apportioned",
  credit: "Credit",
};

const basisLabels: Record<AdjustmentBasis, string> = {
  unallocated: "Unallocated",
  particular_average: "Particular Average (PA)",
  general_average: "General Average (GA)",
  sue_and_labour: "Sue & Labour",
  rdc: "Running Down Clause (RDC)",
  other: "Other",
  not_applicable: "Not applicable",
};

const statusTone: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  under_review: "bg-amber-50 text-amber-800",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
};

export default function AdjustmentWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [financial, setFinancial] = useState<FinancialReviewResponse | null>(null);
  const [items, setItems] = useState<AdjustmentStatement[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currency, setCurrency] = useState("USD");
  const [reviewNote, setReviewNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selected = useMemo(() => items.find((item) => item.id === selectedId) ?? null, [items, selectedId]);
  const canReview = user?.role === "admin" || user?.role === "claims_manager";
  const editable = selected?.status === "draft" || selected?.status === "rejected";

  async function load(preferId?: string) {
    try {
      const [claimData, userData, financialData, statements] = await Promise.all([
        getClaim(id), getCurrentUser(), getFinancialReview(id), listAdjustmentStatements(id),
      ]);
      setClaim(claimData); setUser(userData); setFinancial(financialData);
      setItems(statements.items);
      setCurrency(claimData.currency);
      setSelectedId(preferId ?? selectedId ?? statements.items[0]?.id ?? null);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Adjustment Workspace could not be loaded.");
    }
  }

  useEffect(() => { load(); }, [id]);

  function replaceStatement(updated: AdjustmentStatement) {
    setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
  }

  function patchStatement(patch: Partial<AdjustmentStatement>) {
    if (!selected) return;
    setItems((current) => current.map((item) => item.id === selected.id ? { ...item, ...patch } : item));
  }

  function patchLine(lineId: string, patch: Partial<AdjustmentLine>) {
    if (!selected) return;
    patchStatement({ lines: selected.lines.map((line) => line.id === lineId ? { ...line, ...patch } : line) });
  }

  async function createVersion() {
    setBusy(true); setError("");
    try {
      const created = await createAdjustmentStatement(id, { currency, title: claim ? claim.claim_reference + " – Adjustment Statement" : null });
      setItems((current) => [created, ...current]); setSelectedId(created.id);
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Adjustment draft could not be created."); }
    finally { setBusy(false); }
  }

  async function saveLine(line: AdjustmentLine) {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      replaceStatement(await updateAdjustmentLine(id, selected.id, line.id, {
        treatment: line.treatment,
        basis: line.basis,
        considered_amount: line.considered_amount,
        reason: line.reason,
        note: line.note,
      }));
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Adjustment line could not be saved."); }
    finally { setBusy(false); }
  }

  async function saveStatement() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      replaceStatement(await updateAdjustmentStatement(id, selected.id, {
        title: selected.title,
        deductible_amount: selected.deductible_amount,
        deductible_basis: selected.deductible_basis ?? "",
        other_deduction_amount: selected.other_deduction_amount,
        other_deduction_basis: selected.other_deduction_basis ?? "",
      }));
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Statement controls could not be saved."); }
    finally { setBusy(false); }
  }

  async function transition(action: "submit" | "approve" | "reject") {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = action === "submit"
        ? await submitAdjustmentStatement(id, selected.id)
        : await reviewAdjustmentStatement(id, selected.id, action, reviewNote.trim());
      replaceStatement(updated); setReviewNote("");
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Adjustment status could not be updated."); }
    finally { setBusy(false); }
  }

  if (!claim || !financial) return <div className="panel p-6 text-sm text-slate-600">{error || "Loading Adjustment Workspace…"}</div>;

  const currencies = Array.from(new Set([claim.currency, ...Object.keys(financial.totals_by_currency)]));
  const reserve = financial.reserve_history.find((row) => row.currency === selected?.currency);

  return <div>
    <Link href={"/claims/" + id + "/financial"} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to Financial Review</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
      <div><p className="eyebrow">{claim.claim_reference} · Advanced financial control</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Adjustment Workspace</h1><p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">Build a versioned, source-linked adjustment from reviewed invoice lines. All PA, GA, Sue & Labour, RDC, deductible, betterment and deduction treatments are human decisions. The adjusted total is not payment authority or an automated coverage decision.</p></div>
      <div className="flex gap-2"><select className="field min-w-28" value={currency} onChange={(e) => setCurrency(e.target.value)}>{currencies.map((value) => <option key={value}>{value}</option>)}</select><button className="primary-button whitespace-nowrap" disabled={busy} onClick={createVersion}>Create new version</button></div>
    </div>

    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}

    <div className="mt-6 grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="panel p-4"><h2 className="px-2 text-sm font-semibold text-slate-950">Adjustment versions</h2><p className="px-2 text-xs text-slate-500">Approved versions remain immutable.</p><div className="mt-3 space-y-2">{items.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={"w-full rounded-xl border p-3 text-left " + (item.id === selectedId ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white")}><div className="flex items-center justify-between gap-2"><p className="font-semibold text-slate-900">Version {item.version}</p><span className={"rounded-full px-2 py-1 text-[10px] font-semibold " + (statusTone[item.status] ?? "bg-slate-100")}>{item.status.replaceAll("_", " ")}</span></div><p className="mt-2 text-xs text-slate-500">{item.currency} · {item.lines.length} source line(s)</p><p className="mt-1 text-sm font-semibold text-slate-800">{formatMoney(item.net_adjusted, item.currency)}</p></button>)}{!items.length ? <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">Create the first currency-specific version from current invoice evidence.</div> : null}</div></aside>

      <main>
        {!selected ? <div className="panel p-12 text-center text-sm text-slate-500">No adjustment version selected.</div> : <>
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="panel p-5"><p className="metric-label">Gross claimed</p><p className="metric-value text-xl">{formatMoney(selected.gross_claimed, selected.currency)}</p></div>
            <div className="panel p-5"><p className="metric-label">Gross considered</p><p className="metric-value text-xl">{formatMoney(selected.gross_considered, selected.currency)}</p></div>
            <div className="panel p-5"><p className="metric-label">Adjusted total</p><p className="metric-value text-xl">{formatMoney(selected.net_adjusted, selected.currency)}</p><p className="mt-1 text-xs text-slate-400">Not payment authority</p></div>
            <div className="panel p-5"><p className="metric-label">Current reserve</p><p className="metric-value text-xl">{reserve ? formatMoney(reserve.amount, reserve.currency) : "Not recorded"}</p><p className="mt-1 text-xs text-slate-400">Comparison only; never auto-updated</p></div>
          </section>

          <section className="panel mt-6 p-6">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">Version {selected.version} · {selected.currency}</p>{editable ? <input className="field mt-2 text-lg font-semibold" value={selected.title} onChange={(e) => patchStatement({ title: e.target.value })} /> : <h2 className="mt-1 text-xl font-semibold text-slate-950">{selected.title}</h2>}</div><span className={"rounded-full px-3 py-1.5 text-xs font-semibold " + (statusTone[selected.status] ?? "bg-slate-100")}>{selected.status.replaceAll("_", " ")}</span></div>

            <div className="mt-5 overflow-x-auto"><table className="data-table min-w-[1180px]"><thead><tr><th># / source</th><th>Description</th><th>Claimed</th><th>Treatment</th><th>Basis</th><th>Considered</th><th>Reason / adjustment basis</th><th></th></tr></thead><tbody>{selected.lines.map((line) => <tr key={line.id}><td><p className="font-semibold">{line.sort_order}</p><p className="text-xs text-slate-400">{line.supplier || "Supplier"} {line.document_number || ""}</p></td><td><p className="max-w-xs font-medium text-slate-800">{line.description}</p><p className="text-xs text-slate-400">{line.category || "Uncategorised"}</p></td><td>{formatMoney(line.claimed_amount, selected.currency)}</td><td><select disabled={!editable} className="field min-w-36 py-2 text-xs" value={line.treatment} onChange={(e) => patchLine(line.id, { treatment: e.target.value as AdjustmentTreatment })}>{Object.entries(treatmentLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td><td><select disabled={!editable} className="field min-w-44 py-2 text-xs" value={line.basis} onChange={(e) => patchLine(line.id, { basis: e.target.value as AdjustmentBasis })}>{Object.entries(basisLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td><td><input disabled={!editable} type="number" step="0.01" className="field w-32" value={line.considered_amount} onChange={(e) => patchLine(line.id, { considered_amount: e.target.value })} /></td><td><textarea disabled={!editable} className="field min-h-20 min-w-64 text-xs" value={line.reason ?? ""} onChange={(e) => patchLine(line.id, { reason: e.target.value })} placeholder="Required for exclusions, apportionments, credits and amount differences" /></td><td>{editable ? <button className="secondary-button px-3 py-2 text-xs" disabled={busy} onClick={() => saveLine(line)}>Save line</button> : null}</td></tr>)}</tbody></table></div>
          </section>

          <section className="panel mt-6 p-6"><h2 className="section-title">Statement-level controls</h2><p className="section-subtitle">Amounts are entered by the claims professional; the system performs arithmetic only and does not interpret policy wording.</p><div className="mt-5 grid gap-4 lg:grid-cols-2"><div className="rounded-xl border border-slate-200 p-4"><label><span className="label">Deductible ({selected.currency})</span><input disabled={!editable} type="number" min="0" step="0.01" className="field" value={selected.deductible_amount} onChange={(e) => patchStatement({ deductible_amount: e.target.value })} /></label><label className="mt-3 block"><span className="label">Deductible basis</span><textarea disabled={!editable} className="field min-h-24" value={selected.deductible_basis ?? ""} onChange={(e) => patchStatement({ deductible_basis: e.target.value })} placeholder="Policy clause, wording and human review basis" /></label></div><div className="rounded-xl border border-slate-200 p-4"><label><span className="label">Other deduction / credit ({selected.currency})</span><input disabled={!editable} type="number" min="0" step="0.01" className="field" value={selected.other_deduction_amount} onChange={(e) => patchStatement({ other_deduction_amount: e.target.value })} /></label><label className="mt-3 block"><span className="label">Other deduction / credit basis</span><textarea disabled={!editable} className="field min-h-24" value={selected.other_deduction_basis ?? ""} onChange={(e) => patchStatement({ other_deduction_basis: e.target.value })} placeholder="e.g. residual value, agreed credit or human-reviewed adjustment" /></label></div></div>{editable ? <div className="mt-4 flex flex-wrap gap-2"><button className="secondary-button" disabled={busy} onClick={saveStatement}>Save controls</button><button className="primary-button" disabled={busy} onClick={() => transition("submit")}>Submit for Manager review</button></div> : null}</section>

          {selected.status === "under_review" && canReview ? <section className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-5"><h2 className="text-sm font-semibold text-amber-950">Manager review</h2><p className="mt-1 text-xs leading-5 text-amber-800">Approval confirms human review of line treatments, allocation bases, deductions and arithmetic. It is not payment authorization.</p><textarea className="field mt-3 min-h-24" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Record review against technical evidence, invoices and applicable wording." /><div className="mt-3 flex gap-2"><button className="primary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("approve")}>Approve adjustment</button><button className="secondary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("reject")}>Reject to draft</button></div></section> : null}

          {selected.review_note ? <section className="panel mt-6 p-5"><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">Manager review note</p><p className="mt-2 text-sm text-slate-700">{selected.review_note}</p>{selected.content_hash ? <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Immutable content hash: {selected.content_hash}</p> : null}</section> : null}
        </>}
      </main>
    </div>
  </div>;
}
