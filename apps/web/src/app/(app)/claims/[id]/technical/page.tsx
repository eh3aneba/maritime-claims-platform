"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getClaim, getTechnicalReview } from "@/lib/api";
import type { Claim, TechnicalReviewResponse } from "@/lib/types";

function pretty(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export default function TechnicalReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [review, setReview] = useState<TechnicalReviewResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getClaim(id), getTechnicalReview(id)]).then(([c, r]) => { setClaim(c); setReview(r); })
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Technical review could not be loaded."));
  }, [id]);

  if (!claim && !error) return <div className="py-20 text-center text-sm text-slate-500">Loading technical review…</div>;
  if (!claim || !review) return <div className="panel p-6 text-sm text-red-700">{error || "Technical review unavailable."}</div>;

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to {claim.vessel.name}</Link>
    <div className="mt-5"><p className="eyebrow">{claim.claim_reference}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Technical review matrix</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">Human-approved maintenance facts and reviewed workshop evidence assembled into investigation topics. The matrix does not confirm causation.</p></div>

    <section className="panel mt-7 p-6"><h2 className="section-title">Maintenance facts</h2><p className="section-subtitle">Only human-approved scalar facts can drive deterministic maintenance rules.</p><div className="mt-5 grid gap-3 sm:grid-cols-2">{Object.entries(review.maintenance_facts).map(([key, value]) => <div key={key} className="rounded-xl border border-slate-200 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{key.replaceAll("_", " ")}</p><p className="mt-2 text-sm font-semibold text-slate-900">{pretty(value)}</p></div>)}{Object.keys(review.maintenance_facts).length === 0 ? <p className="text-sm text-slate-500">No approved maintenance facts yet.</p> : null}</div></section>

    <section className="mt-6 space-y-4"><div><h2 className="section-title">Investigation matrix</h2><p className="section-subtitle">Evidence for, evidence against, unknowns and recommended follow-up are kept separate.</p></div>{review.matrix.length ? review.matrix.map((row) => <article key={row.key} className="panel p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">{row.severity} · {row.status}</p><h3 className="mt-1 text-lg font-semibold text-slate-950">{row.title}</h3></div></div><p className="mt-3 text-sm leading-6 text-slate-600">{row.explanation}</p><div className="mt-5 grid gap-4 lg:grid-cols-2"><div className="rounded-xl bg-emerald-50 p-4"><p className="text-xs font-bold uppercase tracking-wide text-emerald-700">Evidence for</p><pre className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">{row.evidence_for.length ? JSON.stringify(row.evidence_for, null, 2) : "No supporting evidence recorded."}</pre></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-600">Evidence against / counter-evidence</p><pre className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">{row.evidence_against.length ? JSON.stringify(row.evidence_against, null, 2) : "No counter-evidence recorded."}</pre></div></div><div className="mt-4 grid gap-4 lg:grid-cols-2"><div><p className="text-xs font-bold uppercase tracking-wide text-amber-700">Unknown / missing</p><ul className="mt-2 space-y-1 text-sm text-slate-700">{row.unknown_or_missing.map((item) => <li key={item}>• {item}</li>)}</ul></div><div><p className="text-xs font-bold uppercase tracking-wide text-cyan-700">Recommended follow-up</p><ul className="mt-2 space-y-1 text-sm text-slate-700">{row.recommended_follow_up.map((item) => <li key={item}>• {item}</li>)}</ul></div></div></article>) : <div className="panel p-8 text-center text-sm text-slate-500">No technical investigation topics yet. Review maintenance/workshop evidence and refresh Rules.</div>}</section>

    <section className="panel mt-6 p-6"><h2 className="section-title">Reviewed workshop evidence</h2><div className="mt-4 grid gap-5 lg:grid-cols-3"><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Damage findings</p><p className="mt-2 text-2xl font-semibold">{review.workshop_findings.length}</p></div><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Repair-option fields</p><p className="mt-2 text-2xl font-semibold">{review.workshop_repair_options.length}</p></div><div><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Cause opinions</p><p className="mt-2 text-2xl font-semibold">{review.workshop_cause_opinions.length}</p></div></div></section>
  </div>;
}
