"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, changeClaimReserve, changeClaimStatus, getClaim, getClaimFacts } from "@/lib/api";
import { formatDate, formatMoney, priorityLabel, statusLabel } from "@/lib/format";
import type { Claim, ClaimFact, ClaimStatus } from "@/lib/types";
import { PriorityText, StatusBadge } from "@/components/status-badge";
import { ClaimDocuments } from "@/components/claim-documents";

const statusFlow: ClaimStatus[] = ["new","triage","awaiting_documents","investigation","technical_review","financial_review","coverage_review","negotiation","settlement","recovery","closed"];

export default function ClaimOverviewPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [approvedFacts, setApprovedFacts] = useState<ClaimFact[]>([]);
  const [error, setError] = useState("");
  const [updating, setUpdating] = useState(false);
  const [reserve, setReserve] = useState("");
  const [reserveReason, setReserveReason] = useState("");

  function load() { Promise.all([getClaim(id), getClaimFacts(id)]).then(([c, facts]) => { setClaim(c); setReserve(c.current_reserve ?? ""); setApprovedFacts(facts.items); }).catch((e) => setError(e instanceof ApiError ? e.detail : "Claim could not be loaded.")); }
  useEffect(() => { load(); }, [id]);

  async function advanceStatus() {
    if (!claim) return;
    const index = statusFlow.indexOf(claim.status);
    if (index < 0 || index >= statusFlow.length - 1) return;
    setUpdating(true); setError("");
    try { setClaim(await changeClaimStatus(claim.id, statusFlow[index + 1], "Advanced from claim overview")); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Status could not be changed."); }
    finally { setUpdating(false); }
  }

  async function saveReserve() {
    if (!claim || !reserve || reserveReason.trim().length < 3) { setError("Enter a reserve amount and a short reason."); return; }
    setUpdating(true); setError("");
    try { const updated = await changeClaimReserve(claim.id, Number(reserve), reserveReason.trim()); setClaim(updated); setReserveReason(""); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Reserve could not be changed. Manager access may be required."); }
    finally { setUpdating(false); }
  }

  if (!claim && !error) return <div className="py-20 text-center text-sm text-slate-500">Loading claim…</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error}</div>;

  const nextIndex = statusFlow.indexOf(claim.status) + 1;
  const nextStatus = nextIndex > 0 && nextIndex < statusFlow.length ? statusFlow[nextIndex] : null;

  return (
    <div>
      <Link href="/claims" className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claims</Link>
      <div className="mt-5 flex flex-col justify-between gap-5 xl:flex-row xl:items-start">
        <div><div className="flex flex-wrap items-center gap-3"><p className="eyebrow">{claim.claim_reference}</p><StatusBadge status={claim.status} /></div><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">{claim.vessel.name}</h1><p className="mt-2 text-sm text-slate-500">H&M · Machinery Damage{claim.vessel.imo_number ? ` · IMO ${claim.vessel.imo_number}` : ""}</p></div>
        <div className="flex flex-wrap gap-3">{nextStatus ? <button disabled={updating} onClick={advanceStatus} className="secondary-button">Advance to {statusLabel[nextStatus]}</button> : null}<button className="primary-button" onClick={() => document.getElementById("claim-evidence")?.scrollIntoView({ behavior: "smooth" })}>Upload document</button></div>
      </div>

      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">Incident date</p><p className="metric-value text-xl">{formatDate(claim.incident_date)}</p></div>
        <div className="panel p-5"><p className="metric-label">Priority</p><div className="mt-3"><PriorityText priority={claim.priority} /></div><p className="mt-2 text-xs text-slate-400">{priorityLabel[claim.priority]} case attention</p></div>
        <div className="panel p-5"><p className="metric-label">Estimated loss</p><p className="metric-value">{formatMoney(claim.estimated_loss, claim.currency)}</p></div>
        <div className="panel p-5"><p className="metric-label">Current reserve</p><p className="metric-value">{formatMoney(claim.current_reserve, claim.currency)}</p></div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <section className="panel p-6"><div className="flex items-center justify-between"><div><h2 className="section-title">Claim overview</h2><p className="section-subtitle">Core incident facts currently recorded in the system.</p></div></div><dl className="mt-6 grid gap-x-10 gap-y-5 sm:grid-cols-2"><div><dt className="detail-label">Status</dt><dd className="detail-value">{statusLabel[claim.status]}</dd></div><div><dt className="detail-label">Handler</dt><dd className="detail-value">{claim.handler?.full_name ?? "Unassigned"}</dd></div><div><dt className="detail-label">Notification date</dt><dd className="detail-value">{formatDate(claim.notification_date)}</dd></div><div><dt className="detail-label">External reference</dt><dd className="detail-value">{claim.external_reference ?? "—"}</dd></div></dl><div className="mt-6 border-t border-slate-200 pt-5"><p className="detail-label">Incident description</p><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{claim.incident_description}</p></div></section>

          <section className="panel p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><h2 className="section-title">Approved claim facts</h2><p className="section-subtitle">Human-approved structured facts. AI candidates appear here only after explicit review.</p></div><Link href={`/ai-review?claim_id=${claim.id}`} className="secondary-button whitespace-nowrap">Review AI evidence</Link></div>{approvedFacts.length ? <div className="mt-5 overflow-x-auto"><table className="data-table"><thead><tr><th>Field</th><th>Approved value</th><th>Version</th><th>Approved</th></tr></thead><tbody>{approvedFacts.map((fact) => <tr key={fact.id}><td><div className="font-medium text-slate-800">{fact.field_path.replaceAll("_", " ")}</div></td><td><div className="max-w-xl break-words font-medium text-slate-800">{typeof fact.value === "object" ? JSON.stringify(fact.value) : String(fact.value ?? "—")}</div></td><td>v{fact.version}</td><td>{formatDate(fact.approved_at)}</td></tr>)}</tbody></table></div> : <div className="mt-5 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center text-sm text-slate-500">No AI-derived facts have been approved yet.</div>}</section>

          <div id="claim-evidence"><ClaimDocuments claimId={claim.id} /></div>
        </div>

        <aside className="space-y-5">
          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">AI evidence review</h2><p className="mt-1 text-xs leading-5 text-slate-500">Review source-linked AI candidates before they become approved claim facts.</p><Link href={`/ai-review?claim_id=${claim.id}`} className="secondary-button mt-4 w-full justify-center">Open AI review queue</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Initial assessment</h2><p className="mt-1 text-xs leading-5 text-slate-500">Assemble approved evidence, chronology, rules, costs, reserve and next actions into a versioned human-reviewed assessment.</p><Link href={`/claims/${claim.id}/assessment`} className="secondary-button mt-4 w-full justify-center">Open initial assessment</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Financial review</h2><p className="mt-1 text-xs leading-5 text-slate-500">Compare reviewed quotations, invoice line items, cost flags and reserve history without automatic recoverability decisions.</p><Link href={`/claims/${claim.id}/financial`} className="secondary-button mt-4 w-full justify-center">Open financial review</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Correspondence Centre</h2><p className="mt-1 text-xs leading-5 text-slate-500">Draft, review and file formal claim communications without connecting a mailbox or sending email automatically.</p><Link href={`/claims/${claim.id}/correspondence`} className="secondary-button mt-4 w-full justify-center">Open correspondence centre</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Controlled Email Intake</h2><p className="mt-1 text-xs leading-5 text-slate-500">Review consent-gated inbound email before any human-confirmed claim link; attachment manifests remain outside active evidence.</p><Link href={`/claims/${claim.id}/email-intake`} className="secondary-button mt-4 w-full justify-center">Open controlled email intake</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Email Adapter Operations</h2><p className="mt-1 text-xs leading-5 text-slate-500">Operate least-privilege provider adapters with bounded runs, secret references and scheduled retention.</p><Link href={`/claims/${claim.id}/email-adapters`} className="secondary-button mt-4 w-full justify-center">Open email adapter operations</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">External Collaboration Portal</h2><p className="mt-1 text-xs leading-5 text-slate-500">Invite a named external participant into a short-lived, claim-scoped and explicitly published workspace.</p><Link href={`/claims/${claim.id}/external-portal`} className="secondary-button mt-4 w-full justify-center">Open external collaboration portal</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Adjustment Workspace</h2><p className="mt-1 text-xs leading-5 text-slate-500">Build versioned PA, GA, Sue &amp; Labour and RDC adjustment drafts from reviewed invoice costs with Manager approval.</p><Link href={`/claims/${claim.id}/adjustment`} className="secondary-button mt-4 w-full justify-center">Open adjustment workspace</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Settlement &amp; Payment Ledger</h2><p className="mt-1 text-xs leading-5 text-slate-500">Control settlement proposals and four-eyes payment authorization without sending offers, contacting banks or moving money.</p><Link href={`/claims/${claim.id}/settlement-payments`} className="secondary-button mt-4 w-full justify-center">Open settlement and payment ledger</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Policy &amp; Contract Intelligence</h2><p className="mt-1 text-xs leading-5 text-slate-500">Review source-linked limits, deductibles, periods, clauses, exclusions, warranties, notice requirements and time bars without an automated coverage decision.</p><Link href={`/claims/${claim.id}/policy-intelligence`} className="secondary-button mt-4 w-full justify-center">Open policy intelligence</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Technical review</h2><p className="mt-1 text-xs leading-5 text-slate-500">Review approved maintenance facts, workshop findings, source opinions and deterministic technical investigation flags.</p><Link href={`/claims/${claim.id}/technical`} className="secondary-button mt-4 w-full justify-center">Open technical review</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Evidence Matrix</h2><p className="mt-1 text-xs leading-5 text-slate-500">Review approved facts, supporting document versions and active conflicts in one source-linked view.</p><Link href={`/claims/${claim.id}/evidence-matrix`} className="secondary-button mt-4 w-full justify-center">Open evidence matrix</Link></section>\n\n          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Claim-pack exports</h2><p className="mt-1 text-xs leading-5 text-slate-500">Create immutable PDF or Excel snapshots that preserve approved facts, source versions, open conflicts, missing evidence and file hashes.</p><Link href={`/claims/${claim.id}/claim-pack`} className="secondary-button mt-4 w-full justify-center">Open claim-pack exports</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Chronology & conflicts</h2><p className="mt-1 text-xs leading-5 text-slate-500">Build a timeline from reviewed evidence and inspect material discrepancies without adjudicating source truth.</p><Link href={`/claims/${claim.id}/chronology`} className="secondary-button mt-4 w-full justify-center">Open chronology</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Requirements & rules</h2><p className="mt-1 text-xs leading-5 text-slate-500">See current-stage missing evidence, blocking items, readiness and explainable rule-generated investigation flags.</p><Link href={`/claims/${claim.id}/rules`} className="secondary-button mt-4 w-full justify-center">Open requirements</Link></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Workflow</h2><div className="mt-4 space-y-3">{statusFlow.slice(0, 7).map((s) => { const current = s === claim.status; const passed = statusFlow.indexOf(s) < statusFlow.indexOf(claim.status); return <div key={s} className="flex items-center gap-3"><span className={`h-2.5 w-2.5 rounded-full ${current ? "bg-cyan-600 ring-4 ring-cyan-100" : passed ? "bg-emerald-500" : "bg-slate-200"}`} /><span className={`text-sm ${current ? "font-semibold text-slate-950" : passed ? "text-slate-600" : "text-slate-400"}`}>{statusLabel[s]}</span></div>; })}</div></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">Reserve control</h2><p className="mt-1 text-xs leading-5 text-slate-500">Manager/admin controlled. Full reserve history is scheduled for a later financial module.</p><label className="mt-4 block"><span className="label">Amount ({claim.currency})</span><input type="number" min="0" value={reserve} onChange={(e) => setReserve(e.target.value)} className="field" /></label><label className="mt-3 block"><span className="label">Reason</span><textarea rows={3} value={reserveReason} onChange={(e) => setReserveReason(e.target.value)} className="field resize-none" placeholder="e.g. Replacement quotation received" /></label><button onClick={saveReserve} disabled={updating} className="secondary-button mt-3 w-full justify-center">Update reserve</button></section>
        </aside>
      </div>
    </div>
  );
}
