"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, getClaim, getClaimChronology, rebuildClaimChronology, resolveEvidenceConflict } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import type { Claim, ClaimChronologyResponse, ChronologyEvidence, EvidenceConflict, EvidenceConflictStatus } from "@/lib/types";

const materialityClasses: Record<string, string> = {
  low: "bg-slate-100 text-slate-600",
  medium: "bg-amber-50 text-amber-800",
  high: "bg-orange-50 text-orange-800",
  critical: "bg-red-50 text-red-800",
};

const measurementKeys = new Set(["rpm", "engine_load", "turbocharger_speed", "exhaust_temperature", "lube_oil_pressure"]);

function evidenceLeaf(path: string) {
  return path.split(".").at(-1) ?? path;
}

function cleanEventDescription(description: string | null) {
  if (!description) return null;
  const kept = description
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .filter((part) => !/^(RPM|Load|TC speed|Exhaust temp|Lube oil pressure):/i.test(part));
  return kept.join("; ") || null;
}

function sourceNames(evidence: ChronologyEvidence[]) {
  return Array.from(new Set(evidence.map((item) => item.document_name).filter(Boolean)));
}

function measurementEvidence(evidence: ChronologyEvidence[]) {
  const seen = new Set<string>();
  const rows: Array<{ label: string; value: string }> = [];
  for (const item of evidence) {
    const leaf = evidenceLeaf(item.field_path);
    if (!measurementKeys.has(leaf) || seen.has(leaf)) continue;
    seen.add(leaf);
    const labelMap: Record<string, string> = {
      rpm: "RPM",
      engine_load: "Engine load",
      turbocharger_speed: "Turbocharger speed",
      exhaust_temperature: "Exhaust temperature",
      lube_oil_pressure: "Lube oil pressure",
    };
    rows.push({ label: labelMap[leaf] ?? humanizeFieldLabel(leaf), value: formatStructuredValue(item.value) });
  }
  return rows;
}

function formatConflictValue(value: unknown) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (record.date || record.time) {
      return [record.date, record.time, record.timezone].filter(Boolean).join(" ");
    }
  }
  return formatStructuredValue(value);
}

export default function ClaimChronologyPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [chronology, setChronology] = useState<ClaimChronologyResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<Record<string, string>>({});

  async function load() {
    try {
      const [claimData, chronologyData] = await Promise.all([getClaim(id), getClaimChronology(id)]);
      setClaim(claimData);
      setChronology(chronologyData);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Chronology could not be loaded.");
    }
  }

  useEffect(() => { load(); }, [id]);

  async function rebuild() {
    setBusy(true); setError("");
    try { await rebuildClaimChronology(id); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Chronology could not be rebuilt."); }
    finally { setBusy(false); }
  }

  async function resolve(conflict: EvidenceConflict, status: Exclude<EvidenceConflictStatus, "open">) {
    const note = (notes[conflict.id] ?? "").trim();
    if (note.length < 3) { setError("Add a short explanation before resolving a conflict."); return; }
    setBusy(true); setError("");
    try {
      await resolveEvidenceConflict(id, conflict.id, { status, note });
      setNotes((current) => ({ ...current, [conflict.id]: "" }));
      await load();
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Conflict could not be updated."); }
    finally { setBusy(false); }
  }

  const sourceCount = useMemo(() => {
    if (!chronology) return 0;
    return new Set(chronology.events.flatMap((event) => event.evidence.map((e) => e.document_id))).size;
  }, [chronology]);

  if (!claim || !chronology) return <div className="py-20 text-center text-sm text-slate-500">{error || "Loading chronology…"}</div>;

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claim</Link>
      <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <p className="eyebrow">{claim.claim_reference}</p>
          <h1 className="page-title">Claim chronology</h1>
          <p className="page-subtitle">Human-reviewed evidence aligned into a single timeline. Conflicts are review flags only; the system does not decide which source is factually correct.</p>
        </div>
        <button className="primary-button" disabled={busy} onClick={rebuild}>{busy ? "Refreshing…" : "Build / refresh chronology"}</button>
      </div>

      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-3">
        <div className="panel p-5"><p className="metric-label">Timeline events</p><p className="metric-value">{chronology.event_count}</p></div>
        <div className="panel p-5"><p className="metric-label">Open evidence conflicts</p><p className="metric-value">{chronology.open_conflict_count}</p></div>
        <div className="panel p-5"><p className="metric-label">Reviewed source documents</p><p className="metric-value">{sourceCount}</p></div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="panel p-6">
          <h2 className="section-title">Chronology</h2>
          <p className="section-subtitle">Events within ten minutes may be clustered when they describe the same event type. For display purposes only, an Engine Log timestamp may be used as the canonical time inside a compatible cluster; this does not determine which evidence is true.</p>
          {chronology.events.length ? <div className="mt-7 space-y-0">
            {chronology.events.map((event, index) => {
              const sources = sourceNames(event.evidence);
              const measurements = measurementEvidence(event.evidence);
              const description = cleanEventDescription(event.description);
              return <div key={event.id} className="relative grid grid-cols-[100px_24px_minmax(0,1fr)] gap-3 pb-8 last:pb-0">
                <div className="pt-0.5 text-right"><div className="text-sm font-semibold text-slate-900">{event.occurred_time ? event.occurred_time.slice(0,5) : "Time not stated"}</div><div className="mt-1 text-xs text-slate-400">{event.occurred_on ?? "Relative / undated"}{event.timezone_label ? ` · ${event.timezone_label}` : ""}</div></div>
                <div className="relative flex justify-center"><span className="z-10 mt-1 h-3 w-3 rounded-full bg-cyan-700 ring-4 ring-cyan-50" />{index < chronology.events.length - 1 ? <span className="absolute bottom-[-6px] top-4 w-px bg-slate-200" /> : null}</div>
                <div className="pb-1">
                  <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-950">{event.title}</h3><span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[event.materiality]}`}>Event importance: {event.materiality}</span></div>
                  {sources.length ? <p className="mt-1 text-xs text-slate-500">Source{sources.length > 1 ? "s" : ""}: {sources.join(" · ")}</p> : null}
                  {description ? <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p> : null}
                  {measurements.length ? <div className="mt-3 grid gap-2 sm:grid-cols-2">{measurements.map((row) => <div key={row.label} className="rounded-lg bg-slate-50 px-3 py-2"><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{row.label}</p><p className="mt-1 text-sm font-semibold text-slate-800">{row.value}</p></div>)}</div> : null}
                  <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">Sources ({sources.length}) · Evidence fields ({event.evidence.length})</summary><div className="mt-3 space-y-3">{event.evidence.map((evidence) => <div key={evidence.extraction_id} className="border-t border-slate-200 pt-3 first:border-0 first:pt-0"><div className="flex flex-wrap gap-2 text-xs"><span className="font-semibold text-slate-800">{evidence.document_name}</span><span className="text-slate-400">{humanizeFieldLabel(evidence.field_path)}</span>{evidence.source_verified ? <span className="text-emerald-700">Source verified</span> : <span className="text-amber-700">Manual verification</span>}</div><p className="mt-1 text-xs text-slate-500">Value: {formatStructuredValue(evidence.value)}</p>{evidence.source_quote ? <p className="mt-1 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-500">{evidence.source_quote}</p> : null}</div>)}</div></details>
                </div>
              </div>;
            })}
          </div> : <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">No chronology has been built from reviewed evidence yet.</div>}
        </section>

        <aside className="space-y-5">
          <section className="panel p-5"><h2 className="section-title">Evidence conflicts</h2><p className="section-subtitle">A conflict is a review flag, not a finding about which evidence is true.</p>
            {chronology.conflicts.length ? <div className="mt-5 space-y-4">{chronology.conflicts.map((conflict) => <div key={conflict.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-slate-950">{conflict.topic}</p><p className="mt-1 text-xs uppercase tracking-wide text-slate-400">{conflict.conflict_type} · {conflict.status.replaceAll("_", " ")}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[conflict.materiality]}`}>Conflict severity: {conflict.materiality}</span></div><p className="mt-3 text-sm leading-6 text-slate-600">{conflict.description}</p><div className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><div><span className="font-semibold">A:</span> {formatConflictValue(conflict.value_a)}</div><div><span className="font-semibold">B:</span> {formatConflictValue(conflict.value_b)}</div>{conflict.difference_minutes ? <div><span className="font-semibold">Difference:</span> {conflict.difference_minutes} minutes</div> : null}</div>
                {conflict.status === "open" ? <><textarea className="field mt-3 min-h-20" placeholder="Explain how this difference should be understood…" value={notes[conflict.id] ?? ""} onChange={(e) => setNotes((current) => ({ ...current, [conflict.id]: e.target.value }))} /><div className="mt-2 flex flex-wrap gap-2"><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"explained")}>Explain</button><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"accepted_difference")}>Accept difference</button><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"resolved")}>Resolve</button><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"irrelevant")}>Mark irrelevant</button></div></> : conflict.resolution_note ? <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><span className="font-semibold">Review note:</span> {conflict.resolution_note}</div> : null}
              </div>)}</div> : <p className="mt-4 text-sm text-slate-500">No evidence conflicts are currently recorded.</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
