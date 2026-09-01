"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { getSeverityReserve, type SeverityReserveSnapshot } from "@/lib/severity-reserve-api";

function amount(value: string | number | null, currency: string | null) {
  if (value === null || value === undefined || !currency) return "Not calculated";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return `${currency} ${String(value)}`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(parsed);
}

export default function SeverityReserveProxy({ claimId }: { claimId: string }) {
  const [snapshot, setSnapshot] = useState<SeverityReserveSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getSeverityReserve(claimId)
      .then((dashboard) => { if (active) setSnapshot(dashboard.snapshot); })
      .catch((e) => { if (active) setError(e instanceof ApiError ? e.detail : "Severity/reserve support could not be loaded."); });
    return () => { active = false; };
  }, [claimId]);

  const severity = snapshot?.evaluations.find((row) => row.kind === "severity") ?? null;
  const reserve = snapshot?.evaluations.find((row) => row.kind === "reserve") ?? null;

  return <section className="panel p-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">Phase 12D · read-only adjunct</p><h2 className="section-title mt-2">Severity & Reserve Support</h2><p className="section-subtitle">Latest support snapshot is shown here without becoming part of the Claims Intelligence snapshot hash or creating a circular build dependency.</p></div>
      <Link href={`/claims/${claimId}/severity-reserve`} className="secondary-button">Open support workspace</Link>
    </div>
    {error ? <p className="mt-4 text-sm text-rose-700">{error}</p> : null}
    {!snapshot ? <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">No Phase 12D support snapshot exists yet. Build it in the dedicated workspace after reviewing monetary evidence.</div> : <div className="mt-5 grid gap-4 sm:grid-cols-3">
      <div className="rounded-xl border border-slate-200 p-4"><p className="metric-label">Handling priority</p><p className="mt-2 text-xl font-semibold capitalize text-slate-950">{severity?.severity_label ?? "Not available"}</p><p className="mt-1 text-xs text-slate-500">Score {severity?.severity_score ?? 0} · workflow priority only</p></div>
      <div className="rounded-xl border border-slate-200 p-4"><p className="metric-label">Reserve review status</p><p className="mt-2 text-sm font-semibold capitalize text-slate-950">{(reserve?.status ?? "not available").replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-500">No authoritative reserve mutation</p></div>
      <div className="rounded-xl border border-slate-200 p-4"><p className="metric-label">Evidence-grounded range</p><p className="mt-2 text-sm font-semibold text-slate-950">{reserve?.status === "triggered" ? `${amount(reserve.lower_amount, reserve.currency)} – ${amount(reserve.upper_amount, reserve.currency)}` : "Not calculated"}</p><p className="mt-1 text-xs text-slate-500">Snapshot v{snapshot.snapshot_version} · {snapshot.engine_version}</p></div>
    </div>}
  </section>;
}
