"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim, getClaimChronology, rebuildClaimChronology, resolveEvidenceConflict } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import {
  chronologyT,
  conflictStatusLabel,
  conflictTypeLabel,
  materialityLabel,
  type ChronologyKey,
} from "@/lib/i18n-chronology";
import type { Locale } from "@/lib/i18n";
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

function measurementEvidence(evidence: ChronologyEvidence[], locale: Locale) {
  const seen = new Set<string>();
  const rows: Array<{ label: string; value: string }> = [];
  const labelKeys: Record<string, ChronologyKey> = {
    rpm: "measurement.rpm",
    engine_load: "measurement.engine_load",
    turbocharger_speed: "measurement.turbocharger_speed",
    exhaust_temperature: "measurement.exhaust_temperature",
    lube_oil_pressure: "measurement.lube_oil_pressure",
  };
  for (const item of evidence) {
    const leaf = evidenceLeaf(item.field_path);
    if (!measurementKeys.has(leaf) || seen.has(leaf)) continue;
    seen.add(leaf);
    rows.push({
      label: labelKeys[leaf] ? chronologyT(locale, labelKeys[leaf]) : humanizeFieldLabel(leaf),
      value: formatStructuredValue(item.value),
    });
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
  const { locale } = useLocale();
  const ct = (key: ChronologyKey, values?: Record<string, string | number>) => chronologyT(locale, key, values);
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
      setError(e instanceof ApiError ? e.detail : ct("loadError"));
    }
  }

  useEffect(() => { load(); }, [id]);

  async function rebuild() {
    setBusy(true); setError("");
    try { await rebuildClaimChronology(id); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : ct("rebuildError")); }
    finally { setBusy(false); }
  }

  async function resolve(conflict: EvidenceConflict, status: Exclude<EvidenceConflictStatus, "open">) {
    const note = (notes[conflict.id] ?? "").trim();
    if (note.length < 3) { setError(ct("noteRequired")); return; }
    setBusy(true); setError("");
    try {
      await resolveEvidenceConflict(id, conflict.id, { status, note });
      setNotes((current) => ({ ...current, [conflict.id]: "" }));
      await load();
    } catch (e) { setError(e instanceof ApiError ? e.detail : ct("conflictUpdateError")); }
    finally { setBusy(false); }
  }

  const sourceCount = useMemo(() => {
    if (!chronology) return 0;
    return new Set(chronology.events.flatMap((event) => event.evidence.map((e) => e.document_id))).size;
  }, [chronology]);

  if (!claim || !chronology) {
    return <div className="py-20 text-center text-sm text-slate-500">{error || ct("loading")}</div>;
  }

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{ct("backToClaim")}</Link>
      <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <p className="eyebrow" dir="ltr">{claim.claim_reference}</p>
          <h1 className="page-title">{ct("title")}</h1>
          <p className="page-subtitle">{ct("subtitle")}</p>
        </div>
        <button className="primary-button" disabled={busy} onClick={rebuild}>{busy ? ct("refreshing") : ct("buildRefresh")}</button>
      </div>

      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">{error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-3">
        <div className="panel p-5"><p className="metric-label">{ct("metric.events")}</p><p className="metric-value" dir="ltr">{chronology.event_count}</p></div>
        <div className="panel p-5"><p className="metric-label">{ct("metric.openConflicts")}</p><p className="metric-value" dir="ltr">{chronology.open_conflict_count}</p></div>
        <div className="panel p-5"><p className="metric-label">{ct("metric.sources")}</p><p className="metric-value" dir="ltr">{sourceCount}</p></div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="panel p-6">
          <h2 className="section-title">{ct("section.chronology")}</h2>
          <p className="section-subtitle">{ct("section.chronologyHelp")}</p>
          {chronology.events.length ? <div className="mt-7 space-y-0">
            {chronology.events.map((event, index) => {
              const sources = sourceNames(event.evidence);
              const measurements = measurementEvidence(event.evidence, locale);
              const description = cleanEventDescription(event.description);
              const importance = materialityLabel(locale, event.materiality);
              return <div key={event.id} className="relative grid grid-cols-[100px_24px_minmax(0,1fr)] gap-3 pb-8 last:pb-0">
                <div className="pt-0.5 text-right"><div className="text-sm font-semibold text-slate-900" dir={event.occurred_time ? "ltr" : undefined}>{event.occurred_time ? event.occurred_time.slice(0,5) : ct("timeNotStated")}</div><div className="mt-1 text-xs text-slate-400"><span dir={event.occurred_on ? "ltr" : undefined}>{event.occurred_on ?? ct("relativeUndated")}</span>{event.timezone_label ? <span dir="ltr"> · {event.timezone_label}</span> : null}</div></div>
                <div className="relative flex justify-center"><span className="z-10 mt-1 h-3 w-3 rounded-full bg-cyan-700 ring-4 ring-cyan-50" />{index < chronology.events.length - 1 ? <span className="absolute bottom-[-6px] top-4 w-px bg-slate-200" /> : null}</div>
                <div className="pb-1">
                  <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-950" dir="auto">{event.title}</h3><span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[event.materiality]}`}>{ct("eventImportance", { value: importance })}</span></div>
                  {sources.length ? <p className="mt-1 text-xs text-slate-500"><span>{ct(sources.length > 1 ? "source.many" : "source.one")}:</span>{" "}<span dir="ltr">{sources.join(" · ")}</span></p> : null}
                  {description ? <p className="mt-2 text-sm leading-6 text-slate-600" dir="auto">{description}</p> : null}
                  {measurements.length ? <div className="mt-3 grid gap-2 sm:grid-cols-2">{measurements.map((row) => <div key={row.label} className="rounded-lg bg-slate-50 px-3 py-2"><p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{row.label}</p><p className="mt-1 text-sm font-semibold text-slate-800" dir="ltr">{row.value}</p></div>)}</div> : null}
                  <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">{ct("sourcesEvidence", { sources: sources.length, evidence: event.evidence.length })}</summary><div className="mt-3 space-y-3">{event.evidence.map((evidence) => <div key={evidence.extraction_id} className="border-t border-slate-200 pt-3 first:border-0 first:pt-0"><div className="flex flex-wrap gap-2 text-xs"><span className="font-semibold text-slate-800" dir="ltr">{evidence.document_name}</span><span className="text-slate-400" dir="ltr">{humanizeFieldLabel(evidence.field_path)}</span>{evidence.source_verified ? <span className="text-emerald-700">{ct("sourceVerified")}</span> : <span className="text-amber-700">{ct("manualVerification")}</span>}</div><p className="mt-1 text-xs text-slate-500"><span>{ct("value")}:</span>{" "}<span dir="ltr">{formatStructuredValue(evidence.value)}</span></p>{evidence.source_quote ? <p className="mt-1 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-500" dir="auto">{evidence.source_quote}</p> : null}</div>)}</div></details>
                </div>
              </div>;
            })}
          </div> : <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">{ct("emptyChronology")}</div>}
        </section>

        <aside className="space-y-5">
          <section className="panel p-5"><h2 className="section-title">{ct("section.conflicts")}</h2><p className="section-subtitle">{ct("section.conflictsHelp")}</p>
            {chronology.conflicts.length ? <div className="mt-5 space-y-4">{chronology.conflicts.map((conflict) => {
              const severity = materialityLabel(locale, conflict.materiality);
              return <div key={conflict.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-slate-950" dir="auto">{conflict.topic}</p><p className="mt-1 text-xs uppercase tracking-wide text-slate-400">{conflictTypeLabel(locale, conflict.conflict_type)} · {conflictStatusLabel(locale, conflict.status)}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[conflict.materiality]}`}>{ct("conflictSeverity", { value: severity })}</span></div><p className="mt-3 text-sm leading-6 text-slate-600" dir="auto">{conflict.description}</p><div className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><div><span className="font-semibold">A:</span>{" "}<span dir="ltr">{formatConflictValue(conflict.value_a)}</span></div><div><span className="font-semibold">B:</span>{" "}<span dir="ltr">{formatConflictValue(conflict.value_b)}</span></div>{conflict.difference_minutes ? <div><span className="font-semibold">{ct("difference")}:</span>{" "}<span dir="ltr">{conflict.difference_minutes}</span> {ct("minutes")}</div> : null}</div>
                {conflict.status === "open" ? <><textarea className="field mt-3 min-h-20" placeholder={ct("notePlaceholder")} value={notes[conflict.id] ?? ""} onChange={(e) => setNotes((current) => ({ ...current, [conflict.id]: e.target.value }))} dir="auto" /><div className="mt-2 flex flex-wrap gap-2"><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"explained")}>{ct("action.explain")}</button><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"accepted_difference")}>{ct("action.acceptDifference")}</button><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"resolved")}>{ct("action.resolve")}</button><button disabled={busy} className="secondary-button" onClick={() => resolve(conflict,"irrelevant")}>{ct("action.irrelevant")}</button></div></> : conflict.resolution_note ? <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><span className="font-semibold">{ct("reviewNote")}:</span>{" "}<span dir="auto">{conflict.resolution_note}</span></div> : null}
              </div>;
            })}</div> : <p className="mt-4 text-sm text-slate-500">{ct("emptyConflicts")}</p>}
          </section>
        </aside>
      </div>
    </div>
  );
}
