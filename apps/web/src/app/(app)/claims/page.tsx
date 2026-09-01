"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { ApiError, listClaims } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { Claim, ClaimPriority, ClaimStatus } from "@/lib/types";
import { PriorityText, StatusBadge } from "@/components/status-badge";

export default function ClaimsPage() {
  const [items, setItems] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(params = new URLSearchParams()) {
    setLoading(true);
    try {
      params.set("limit", "100");
      const result = await listClaims(params);
      setItems(result.items);
      setTotal(result.total);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Claims could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function filter(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    load(params);
  }

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div><p className="eyebrow">Case portfolio</p><h1 className="page-title">Claims</h1><p className="page-subtitle">Search, filter and open the claims in your organization.</p></div>
        <Link href="/claims/new" className="primary-button">+ New claim</Link>
      </div>

      {error ? <div className="mt-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div> : null}

      <form onSubmit={filter} className="panel mt-7 grid gap-3 p-4 md:grid-cols-[1fr_220px_180px_auto]">
        <input value={search} onChange={(e) => setSearch(e.target.value)} className="field" placeholder="Search claim, vessel or IMO…" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="field"><option value="">All statuses</option>{(["new","triage","awaiting_documents","investigation","technical_review","financial_review","coverage_review","negotiation","settlement","recovery","closed","on_hold","litigation","rejected","withdrawn"] as ClaimStatus[]).map((s) => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}</select>
        <select value={priority} onChange={(e) => setPriority(e.target.value)} className="field"><option value="">All priorities</option>{(["low","medium","high","critical"] as ClaimPriority[]).map((p) => <option key={p} value={p}>{p}</option>)}</select>
        <button className="secondary-button">Apply filters</button>
      </form>

      <section className="panel mt-5 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4"><p className="text-sm text-slate-500">{loading ? "Loading…" : `${total} claim${total === 1 ? "" : "s"}`}</p></div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>Claim</th><th>Vessel</th><th>Incident</th><th>Status</th><th>Priority</th><th>Estimate</th><th>Reserve</th><th>Handler</th><th>Intelligence</th></tr></thead>
            <tbody>
              {!loading && items.length === 0 ? <tr><td colSpan={9} className="py-14 text-center text-slate-500">No claims match the current filters.</td></tr> : null}
              {items.map((claim) => <tr key={claim.id}>
                <td><Link href={`/claims/${claim.id}`} className="font-semibold text-slate-950 hover:text-cyan-800">{claim.claim_reference}</Link>{claim.external_reference ? <div className="mt-1 text-xs text-slate-400">{claim.external_reference}</div> : null}</td>
                <td><div className="font-medium text-slate-800">{claim.vessel.name}</div><div className="text-xs text-slate-400">{claim.vessel.imo_number ? `IMO ${claim.vessel.imo_number}` : "—"}</div></td>
                <td>{formatDate(claim.incident_date)}</td><td><StatusBadge status={claim.status} /></td><td><PriorityText priority={claim.priority} /></td>
                <td>{formatMoney(claim.estimated_loss, claim.currency)}</td><td>{formatMoney(claim.current_reserve, claim.currency)}</td><td>{claim.handler?.full_name ?? <span className="text-slate-400">Unassigned</span>}</td>
                <td><Link href={`/claims/${claim.id}/intelligence`} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">Open intelligence →</Link></td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}