"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getClaim, getTechnicalReview } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import type { Claim, TechnicalEvidenceItem, TechnicalReviewResponse } from "@/lib/types";

function maintenanceLabel(key: string) {
  const labels: Record<string, string> = {
    "maintenance.interval_extension_details": "Interval extension evidence",
    "maintenance.last_overhaul_date": "Last overhaul date",
    "maintenance.recommended_overhaul_interval": "Recommended overhaul interval",
    "maintenance.total_running_hours": "Total running hours",
    "maintenance.overhaul_deferred": "Overhaul deferred",
    "maintenance.pms_status": "PMS status",
    "maintenance.running_hours_since_overhaul": "Running hours since overhaul",
    "workshop.repairable": "Workshop considers unit repairable",
  };
  return labels[key] ?? humanizeFieldLabel(key);
}

function maintenanceValue(key: string, value: unknown) {
  if (key === "maintenance.interval_extension_details" && String(value).toLowerCase().includes("no approved extension")) {
    return "No maker-approved interval extension evidenced in the reviewed claim file";
  }
  return formatStructuredValue(value);
}

function EvidenceCard({ item }: { item: unknown }) {
  if (item === null || item === undefined) return null;
  if (typeof item !== "object" || Array.isArray(item)) return <p className="text-sm text-slate-700">{formatStructuredValue(item)}</p>;
  const record = item as Record<string, unknown>;
  const technical = record as unknown as TechnicalEvidenceItem;
  const sourceQuote = typeof technical.source_quote === "string" ? technical.source_quote : null;
  const value = Object.prototype.hasOwnProperty.call(record, "value") ? record.value : null;
  const fieldPath = typeof record.field_path === "string" ? record.field_path : null;
  const visibleEntries = Object.entries(record).filter(([key]) => ![
    "extraction_id", "document_id", "source_quote", "source_locator_type", "source_locator_value", "source_verified", "field_path", "value",
  ].includes(key));

  return <div className="rounded-lg border border-slate-200 bg-white p-3">
    {fieldPath ? <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{humanizeFieldLabel(fieldPath)}</p> : null}
    {value !== null && value !== undefined ? <p className="mt-1 text-sm font-semibold text-slate-800">{formatStructuredValue(value)}</p> : null}
    {visibleEntries.length ? <dl className="mt-1 grid gap-1 text-sm">{visibleEntries.map(([key, nested]) => <div key={key} className="flex flex-wrap gap-1"><dt className="font-medium text-slate-500">{humanizeFieldLabel(key)}:</dt><dd className="text-slate-700">{formatStructuredValue(nested)}</dd></div>)}</dl> : null}
    {sourceQuote ? <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-xs leading-5 text-slate-500">{sourceQuote}</blockquote> : null}
    {record.source_verified === true ? <p className="mt-2 text-xs font-medium text-emerald-700">Source verified</p> : null}
  </div>;
}

function EvidenceList({ items, empty }: { items: unknown[]; empty: string }) {
  if (!items.length) return <p className="mt-2 text-sm text-slate-500">{empty}</p>;
  return <div className="mt-3 space-y-2">{items.map((item, index) => <EvidenceCard key={index} item={item} />)}</div>;
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
    <div className="mt-5"><p className="eyebrow">{claim.claim_reference}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Technical review matrix</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">Human-approved maintenance facts and reviewed workshop evidence assembled into investigation topics. The matrix identifies matters for investigation and does not confirm causation.</p></div>

    <section className="panel mt-7 p-6"><h2 className="section-title">Maintenance facts</h2><p className="section-subtitle">Only human-approved scalar facts can drive deterministic maintenance rules.</p><div className="mt-5 grid gap-3 sm:grid-cols-2">{Object.entries(review.maintenance_facts).map(([key, value]) => <div key={key} className="rounded-xl border border-slate-200 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{maintenanceLabel(key)}</p><p className="mt-2 text-sm font-semibold text-slate-900">{maintenanceValue(key, value)}</p></div>)}{Object.keys(review.maintenance_facts).length === 0 ? <p className="text-sm text-slate-500">No approved maintenance facts yet.</p> : null}</div></section>

    <section className="mt-6 space-y-4"><div><h2 className="section-title">Investigation matrix</h2><p className="section-subtitle">Supporting evidence, counter-evidence, unknowns and recommended follow-up are kept separate.</p></div>{review.matrix.length ? review.matrix.map((row) => <article key={row.key} className="panel p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">Investigation priority: {row.severity} · {row.status.replaceAll("_", " ")}</p><h3 className="mt-1 text-lg font-semibold text-slate-950">{row.title}</h3></div></div><p className="mt-3 text-sm leading-6 text-slate-600">{row.explanation}</p><div className="mt-5 grid gap-4 lg:grid-cols-2"><div className="rounded-xl bg-emerald-50 p-4"><p className="text-xs font-bold uppercase tracking-wide text-emerald-700">Evidence for</p><EvidenceList items={row.evidence_for} empty="No supporting evidence recorded." /></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-600">Evidence against / counter-evidence</p><EvidenceList items={row.evidence_against} empty="No counter-evidence recorded." /></div></div><div className="mt-4 grid gap-4 lg:grid-cols-2"><div><p className="text-xs font-bold uppercase tracking-wide text-amber-700">Unknown / missing</p><ul className="mt-2 space-y-1 text-sm text-slate-700">{row.unknown_or_missing.length ? row.unknown_or_missing.map((item) => <li key={item}>• {item}</li>) : <li>• No material unknowns recorded.</li>}</ul></div><div><p className="text-xs font-bold uppercase tracking-wide text-cyan-700">Recommended follow-up</p><ul className="mt-2 space-y-1 text-sm text-slate-700">{row.recommended_follow_up.length ? row.recommended_follow_up.map((item) => <li key={item}>• {item}</li>) : <li>• No system-generated follow-up recorded.</li>}</ul></div></div></article>) : <div className="panel p-8 text-center text-sm text-slate-500">No technical investigation topics yet. Review maintenance/workshop evidence and refresh Rules.</div>}</section>

    <section className="panel mt-6 p-6"><div className="flex items-start justify-between gap-4"><div><h2 className="section-title">Reviewed workshop evidence</h2><p className="section-subtitle">Counts below are evidence fields; expand each category to inspect the human-reviewed content without internal database IDs.</p></div></div><div className="mt-4 grid gap-5 lg:grid-cols-3">
      <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Damage findings</p><p className="mt-2 text-2xl font-semibold">{review.workshop_findings.length}</p></summary><div className="mt-4 space-y-2">{review.workshop_findings.map((item, index) => <EvidenceCard key={index} item={item} />)}</div></details>
      <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Repair-option fields</p><p className="mt-2 text-2xl font-semibold">{review.workshop_repair_options.length}</p></summary><div className="mt-4 space-y-2">{review.workshop_repair_options.map((item, index) => <EvidenceCard key={index} item={item} />)}</div></details>
      <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">Cause opinions</p><p className="mt-2 text-2xl font-semibold">{review.workshop_cause_opinions.length}</p></summary><div className="mt-4 space-y-2">{review.workshop_cause_opinions.map((item, index) => <EvidenceCard key={index} item={item} />)}</div></details>
    </div></section>
  </div>;
}
