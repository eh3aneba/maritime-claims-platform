"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError, createPaymentAuthorization, createSettlementProposal, getClaim, getCurrentUser,
  getSettlementLedger, listAdjustmentStatements, recordPaymentPaidExternally,
  recordSettlementDisposition, reviewPaymentAuthorization, reviewSettlementProposal,
  submitPaymentAuthorization, submitSettlementProposal,
} from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { AdjustmentStatement, Claim, CurrentUser, PaymentAuthorization, SettlementLedger } from "@/lib/types";

const tone: Record<string, string> = {
  approved: "bg-emerald-50 text-emerald-700", accepted: "bg-emerald-50 text-emerald-700",
  authorized: "bg-emerald-50 text-emerald-700", paid_externally: "bg-cyan-50 text-cyan-700",
  under_review: "bg-amber-50 text-amber-800", first_approved: "bg-amber-50 text-amber-800",
  rejected: "bg-red-50 text-red-700", declined: "bg-red-50 text-red-700",
};

export default function SettlementPaymentLedgerPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [adjustments, setAdjustments] = useState<AdjustmentStatement[]>([]);
  const [ledger, setLedger] = useState<SettlementLedger>({ settlements: [], payments: [] });
  const [sourceId, setSourceId] = useState(""); const [amount, setAmount] = useState("");
  const [terms, setTerms] = useState("Full and final settlement subject to signed release.");
  const [payee, setPayee] = useState(""); const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentSettlementId, setPaymentSettlementId] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const approvedAdjustments = useMemo(() => adjustments.filter((x) => x.status === "approved"), [adjustments]);
  const accepted = useMemo(() => ledger.settlements.filter((x) => x.status === "accepted"), [ledger]);
  const canReview = user?.role === "admin" || user?.role === "claims_manager";

  async function load() {
    try {
      const [c, u, a, l] = await Promise.all([getClaim(id), getCurrentUser(), listAdjustmentStatements(id), getSettlementLedger(id)]);
      setClaim(c); setUser(u); setAdjustments(a.items); setLedger(l);
      setSourceId((v) => v || a.items.find((x) => x.status === "approved")?.id || "");
      setPaymentSettlementId((v) => v || l.settlements.find((x) => x.status === "accepted")?.id || "");
      setError("");
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Settlement ledger could not be loaded."); }
  }
  useEffect(() => { load(); }, [id]);
  async function run(task: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await task(); await load(); } catch (e) { setError(e instanceof ApiError ? e.detail : "The controlled action could not be completed."); }
    finally { setBusy(false); }
  }
  async function createSettlement() {
    const source = approvedAdjustments.find((x) => x.id === sourceId);
    if (!source || !amount) return setError("Select an approved adjustment and enter the proposed amount.");
    await run(() => createSettlementProposal(id, {
      adjustment_statement_id: source.id, title: claim!.claim_reference + " – Settlement Proposal",
      settlement_type: "final", amount, terms, release_required: true, without_prejudice: true,
    }));
  }
  async function createPayment() {
    if (!paymentSettlementId || !payee || !paymentAmount) return setError("Select an accepted settlement and enter payee and amount.");
    await run(() => createPaymentAuthorization(id, {
      settlement_id: paymentSettlementId, payee, amount: paymentAmount,
      purpose: "Controlled settlement payment authorization.",
    }));
  }
  function note(label: string) { return window.prompt(label)?.trim() || ""; }
  function paid(item: PaymentAuthorization) {
    const reference = window.prompt("External bank/payment reference"); if (!reference) return;
    const valueDate = window.prompt("Value date (YYYY-MM-DD)", new Date().toISOString().slice(0, 10)); if (!valueDate) return;
    run(() => recordPaymentPaidExternally(id, item.id, {
      confirm_paid_externally: true, channel: "bank_transfer", external_reference: reference, value_date: valueDate,
      note: "Execution evidence checked outside the platform.",
    }));
  }
  if (!claim) return <div className="panel p-6 text-sm text-slate-600">{error || "Loading Settlement & Payment Ledger…"}</div>;
  return <div>
    <Link href={"/claims/" + id + "/adjustment"} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to Adjustment Workspace</Link>
    <p className="eyebrow mt-5">{claim.claim_reference} · human-controlled authority</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Settlement &amp; Payment Ledger</h1>
    <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">Record reviewed settlement proposals and four-eyes payment authorization. The platform never recommends settlement, sends an offer, contacts a bank or moves money.</p>
    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}
    <div className="mt-6 grid gap-6 xl:grid-cols-2">
      <section className="panel p-6"><h2 className="section-title">New settlement proposal</h2><p className="section-subtitle">Source must be an approved immutable adjustment; currency and maximum are inherited.</p>
        <label className="mt-4 block"><span className="label">Approved adjustment</span><select className="field" value={sourceId} onChange={(e) => setSourceId(e.target.value)}><option value="">Select…</option>{approvedAdjustments.map((x) => <option key={x.id} value={x.id}>v{x.version} · {formatMoney(x.net_adjusted, x.currency)}</option>)}</select></label>
        <label className="mt-3 block"><span className="label">Proposed amount</span><input className="field" type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <label className="mt-3 block"><span className="label">Written terms</span><textarea className="field min-h-24" value={terms} onChange={(e) => setTerms(e.target.value)} /></label>
        <button className="primary-button mt-3" disabled={busy || !sourceId} onClick={createSettlement}>Create controlled proposal</button>
      </section>
      <section className="panel p-6"><h2 className="section-title">New payment authorization</h2><p className="section-subtitle">Only accepted settlements are eligible; two different Manager/Admin approvers are required.</p>
        <label className="mt-4 block"><span className="label">Accepted settlement</span><select className="field" value={paymentSettlementId} onChange={(e) => setPaymentSettlementId(e.target.value)}><option value="">Select…</option>{accepted.map((x) => <option key={x.id} value={x.id}>v{x.version} · {formatMoney(x.amount, x.currency)}</option>)}</select></label>
        <label className="mt-3 block"><span className="label">Payee</span><input className="field" value={payee} onChange={(e) => setPayee(e.target.value)} /></label>
        <label className="mt-3 block"><span className="label">Amount</span><input className="field" type="number" min="0" step="0.01" value={paymentAmount} onChange={(e) => setPaymentAmount(e.target.value)} /></label>
        <button className="primary-button mt-3" disabled={busy || !paymentSettlementId} onClick={createPayment}>Create authorization draft</button>
      </section>
    </div>
    <section className="panel mt-6 p-6"><h2 className="section-title">Settlement proposals</h2><div className="mt-4 space-y-3">{ledger.settlements.map((x) => <div key={x.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-slate-900">v{x.version} · {x.title}</p><p className="mt-1 text-sm text-slate-500">{formatMoney(x.amount, x.currency)} · {x.settlement_type} · source adjustment hash {x.source_adjustment_hash.slice(0, 12)}…</p></div><span className={"rounded-full px-3 py-1 text-xs font-semibold " + (tone[x.status] || "bg-slate-100 text-slate-700")}>{x.status.replaceAll("_", " ")}</span></div><p className="mt-3 text-sm text-slate-700">{x.terms}</p><div className="mt-3 flex flex-wrap gap-2">{["draft", "rejected"].includes(x.status) ? <button className="primary-button" disabled={busy} onClick={() => run(() => submitSettlementProposal(id, x.id))}>Submit for Manager review</button> : null}{x.status === "under_review" && canReview ? <><button className="primary-button" disabled={busy} onClick={() => { const n = note("Approval note"); if (n) run(() => reviewSettlementProposal(id, x.id, "approve", n)); }}>Approve</button><button className="secondary-button" disabled={busy} onClick={() => { const n = note("Rejection note"); if (n) run(() => reviewSettlementProposal(id, x.id, "reject", n)); }}>Reject</button></> : null}{x.status === "approved" && canReview ? <button className="primary-button" disabled={busy} onClick={() => { const n = note("Evidence of external acceptance"); if (n) run(() => recordSettlementDisposition(id, x.id, "accepted", n)); }}>Record accepted externally</button> : null}</div>{x.content_hash ? <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Immutable proposal hash: {x.content_hash}</p> : null}</div>)}{!ledger.settlements.length ? <p className="text-sm text-slate-500">No settlement proposals recorded.</p> : null}</div></section>
    <section className="panel mt-6 p-6"><h2 className="section-title">Payment authorization ledger</h2><div className="mt-4 space-y-3">{ledger.payments.map((x) => <div key={x.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-slate-900">Payment #{x.sequence} · {x.payee}</p><p className="mt-1 text-sm text-slate-500">{formatMoney(x.amount, x.currency)} · no bank instruction generated</p></div><span className={"rounded-full px-3 py-1 text-xs font-semibold " + (tone[x.status] || "bg-slate-100 text-slate-700")}>{x.status.replaceAll("_", " ")}</span></div><div className="mt-3 flex flex-wrap gap-2">{["draft", "rejected"].includes(x.status) ? <button className="primary-button" disabled={busy} onClick={() => run(() => submitPaymentAuthorization(id, x.id))}>Submit authorization</button> : null}{["under_review", "first_approved"].includes(x.status) && canReview ? <><button className="primary-button" disabled={busy} onClick={() => { const n = note("Independent approval note"); if (n) run(() => reviewPaymentAuthorization(id, x.id, "approve", n)); }}>{x.status === "under_review" ? "First approval" : "Second independent approval"}</button><button className="secondary-button" disabled={busy} onClick={() => { const n = note("Rejection note"); if (n) run(() => reviewPaymentAuthorization(id, x.id, "reject", n)); }}>Reject</button></> : null}{x.status === "authorized" && canReview ? <button className="primary-button" disabled={busy} onClick={() => paid(x)}>Record paid externally</button> : null}</div>{x.content_hash ? <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Immutable authorization hash: {x.content_hash}</p> : null}{x.external_reference ? <p className="mt-2 text-xs text-slate-500">External reference: {x.external_reference} · value date {x.value_date}</p> : null}</div>)}{!ledger.payments.length ? <p className="text-sm text-slate-500">No payment authorizations recorded.</p> : null}</div></section>
  </div>;
}
