"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { API_BASE } from "@/lib/api";

type IntelligenceItem = {
  id: string;
  category: string;
  title: string;
  latest_decision: { action: string } | null;
};

type IntelligenceDashboard = {
  snapshot: { items: IntelligenceItem[] } | null;
};

const SEARCHABLE_CATEGORIES = new Set([
  "missing_evidence",
  "conflict",
  "hypothesis",
  "issue_flag",
  "recovery_lead",
  "deadline_lead",
]);

export default function EvidenceSearchBridge({ claimId }: { claimId: string }) {
  const [items, setItems] = useState<IntelligenceItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/claims/${claimId}/intelligence`, { credentials: "include" })
      .then(async (response) => response.ok ? response.json() as Promise<IntelligenceDashboard> : null)
      .then((dashboard) => {
        if (cancelled || !dashboard?.snapshot) return;
        setItems(dashboard.snapshot.items);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [claimId]);

  const candidates = useMemo(
    () => items.filter((item) => SEARCHABLE_CATEGORIES.has(item.category) && item.latest_decision?.action !== "dismiss").slice(0, 6),
    [items],
  );

  return (
    <section className="panel p-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="eyebrow">Phase 12E · read-only retrieval bridge</p>
          <h2 className="section-title mt-2">Search evidence behind open intelligence</h2>
          <p className="section-subtitle max-w-3xl">These links only prefill private Evidence Search from current Claims Intelligence items. Search results do not change the intelligence snapshot, create Claim Facts, or resolve the item automatically.</p>
        </div>
        <Link href={`/claims/${claimId}/evidence-search`} className="secondary-button whitespace-nowrap">Open Evidence Search</Link>
      </div>

      {candidates.length ? (
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {candidates.map((item) => (
            <Link
              key={item.id}
              href={`/claims/${claimId}/evidence-search?q=${encodeURIComponent(item.title)}`}
              className="rounded-xl border border-slate-200 p-4 transition hover:border-cyan-300 hover:bg-cyan-50/40"
            >
              <p className="text-[11px] font-bold uppercase tracking-[.12em] text-slate-400">{item.category.replaceAll("_", " ")}</p>
              <p className="mt-2 text-sm font-semibold leading-6 text-slate-900">{item.title}</p>
              <p className="mt-2 text-xs font-semibold text-cyan-700">Search supporting evidence →</p>
            </Link>
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-sm text-slate-500">
          No current Claims Intelligence item needs a prefilled evidence search. You can still open Evidence Search and query the controlled claim file directly.
        </div>
      )}
    </section>
  );
}
