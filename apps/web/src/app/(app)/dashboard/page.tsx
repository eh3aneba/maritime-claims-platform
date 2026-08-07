"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { listClaims } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { Claim } from "@/lib/types";
import { PriorityText, StatusBadge } from "@/components/status-badge";

export default function DashboardPage() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listClaims(new URLSearchParams({ limit: "100" }))
      .then((result) => setClaims(result.items))
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const open = claims.filter((c) => !["closed", "rejected", "withdrawn"].includes(c.status));
    const reserveClaims = open.filter((c) => c.current_reserve !== null);
    const reserveCurrencies = new Set(reserveClaims.map((c) => c.currency));
    const reserve = reserveClaims.reduce((sum, c) => sum + Number(c.current_reserve ?? 0), 0);
    const reserveDisplay = reserveCurrencies.size > 1
      ? "Mixed currencies"
      : formatMoney(reserve, reserveClaims[0]?.currency ?? "USD");
    const urgent = open.filter((c) => ["high", "critical"].includes(c.priority));
    const unassigned = open.filter((c) => !c.handler);
    return { open: open.length, reserveDisplay, urgent: urgent.length, unassigned: unassigned.length };
  }, [claims]);

  const cards = [
    { label: "Open claims", value: loading ? "—" : String(stats.open), hint: "Active case load" },
    { label: "Current reserve", value: loading ? "—" : stats.reserveDisplay, hint: "Across open claims" },
    { label: "High priority", value: loading ? "—" : String(stats.urgent), hint: "Needs closer attention" },
    { label: "Unassigned", value: loading ? "—" : String(stats.unassigned), hint: "No handler assigned" },
  ];

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Claims operations</p>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">A focused view of current H&M machinery claims and immediate workload.</p>
        </div>
        <Link href="/claims/new" className="primary-button">+ New claim</Link>
      </div>

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <article key={card.label} className="panel p-5">
            <p className="text-sm font-medium text-slate-500">{card.label}</p>
            <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">{card.value}</p>
            <p className="mt-2 text-xs text-slate-400">{card.hint}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-950">Recent claims</h2>
            <p className="mt-1 text-sm text-slate-500">Most recent incidents in your organization.</p>
          </div>
          <Link href="/claims" className="text-sm font-semibold text-cyan-800 hover:text-cyan-700">View all</Link>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>Claim</th><th>Vessel</th><th>Incident</th><th>Status</th><th>Priority</th><th>Reserve</th></tr></thead>
            <tbody>
              {!loading && claims.length === 0 ? <tr><td colSpan={6} className="py-12 text-center text-slate-500">No claims yet. Create the first H&M machinery claim.</td></tr> : null}
              {claims.slice(0, 6).map((claim) => (
                <tr key={claim.id}>
                  <td><Link className="font-semibold text-slate-950 hover:text-cyan-800" href={`/claims/${claim.id}`}>{claim.claim_reference}</Link></td>
                  <td><div className="font-medium text-slate-800">{claim.vessel.name}</div><div className="text-xs text-slate-400">{claim.vessel.imo_number ? `IMO ${claim.vessel.imo_number}` : "IMO not recorded"}</div></td>
                  <td>{formatDate(claim.incident_date)}</td>
                  <td><StatusBadge status={claim.status} /></td>
                  <td><PriorityText priority={claim.priority} /></td>
                  <td>{formatMoney(claim.current_reserve, claim.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
