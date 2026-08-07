"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getClaim, getClaimChronology, rebuildClaimChronology, resolveEvidenceConflict } from "@/lib/api";
import type { Claim, ClaimChronologyResponse, EvidenceConflict, EvidenceConflictStatus } from "@/lib/types";

const materialityClasses: Record<string, string> = {
  low: "bg-slate-100 text-slate-600",
  medium: "bg-amber-50 text-amber-800",
  high: "bg-orange-50 text-orange-800",
  critical: "bg-red-50 text-red-800",
};

function renderValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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

  if (!claim || !chronology) return <div className="py-20 text-center text-sm text-slate-500">{error || "Loading chronology…"}</div>;

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claim</Link>
      <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <p className="eyebrow">{claim.claim_reference}</p>
          <h1 className="page-title">Claim chronology</h1>
          <p className="page-subtitle">Human-reviewed evidence aligned into a single timeline. Conflicts are flagged by deterministic rules; the system does not decide which source is correct.</p>
        </div>
        <button className="primary-button" disabled={busy} onClick={rebuild}>{busy ? "Refreshing…" : "Build / refresh chronology"}</button>
      </div>

      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-3">
        <div className="panel p-5"><p className="metric-label">Timeline events</p><p className="metric-value">{chronology.event_count}</p></div>
        <div className="panel p-5"><p className="metric-label">Open evidence conflicts</p><p className="metric-value">{chronology.open_conflict_count}</p></div>
        <div className="panel p-5"><p className="metric-label">Evidence basis</p><p className="mt-3 text-sm font-semibold text-slate-800">Approved / edited AI evidence only</p></div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="panel p-6">
          <h2 className="section-title">Chronology</h2>
          <p className="section-subtitle">Events within ten minutes may be clustered when they describe the same event type. Engine-log timestamps are preferred as the canonical display time inside a cluster.</p>
          {chronology.events.length ? <div className="mt-7 space-y-0">
            {chronology.events.map((event, index) => (
              <div key={event.id} className="relative grid grid-cols-[100px_24px_minmax(0,1fr)] gap-3 pb-8 last:pb-0">
                <div className="pt-0.5 text-right"><div className="text-sm font-semibold text-slate-900">{event.occurred_time.slice(0,5)}</div><div className="mt-1 text-xs text-slate-400">{event.occurred_on}{event.timezone_label ? ` · ${event.timezone_label}` : ""}</div></div>
                <div className="relative flex justify-center"><span className="z-10 mt-1 h-3 w-3 rounded-full bg-cyan-700 ring-4 ring-cyan-50" />{index < chronology.events.length - 1 ? <span className="absolute bottom-[-6px] top-4 w-px bg-slate-200" /> : null}</div>
                <div className="pb-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-950">{event.title}</h3><span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[event.materiality]}`}>{event.materiality}</span></div>{event.description ? <p className="mt-2 text-sm leading-6 text-slate-600">{event.description}</p> : null}
                  <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">Evidence ({event.evidence.length})</summary><div className="mt-3 space-y-3">{event.evidence.map((evidence) => <div key={evidence.extraction_id} className="border-t border-slate-200 pt-3 first:border-0 first:pt-0"><div className="flex flex-wrap gap-2 text-xs"><span className="font-semibold text-slate-800">{evidence.document_name}</span><span className="text-slate-400">{evidence.field_path}</span>{evidence.source_verified ? <span className="text-emerald-700">Source verified</span> : <span className="text-amber-700">Manual verification</span>}</div><p className="mt-1 text-xs text-slate-500">Value: {renderValue(evidence.value)}</p>{evidence.source_quote ? <p className="mt-1 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-500">{evidence.source_quote}</p> : null}</div>)}</div></details>
                </div>
              </div>
            ))}
          </div> : <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">No chronology has been built from reviewed evidence yet.</div>}
        </section>

        <aside className="space-y-5">
          <section className="panel p-5"><h2 className="section-title">Evidence conflicts</h2><p className="section-subtitle">A conflict is a review flag, not a finding about which evidence is true.</p>
            {chronology.conflicts.length ? <div className="mt-5 space-y-4">{chronology.conflicts.map((conflict) => <div key={conflict.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-slate-950">{conflict.topic}</p><p className="mt-1 text-xs uppercase tracking-wide text-slate-400">{conflict.conflict_type} · {conflict.status.replaceAll("_", " ")}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[conflict.materiality]}`}>{conflict.materiality}</span></div><p className="mt-3 text-sm leading-6 text-slate-600">{conflict.description}</p><div className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600"><div><span className="font-semibold">A:</span> {renderValue(conflict.value_a)}</div><div><span className="font-semibold">B:</span> {renderValue(conflict.value_b)}</div>{conflict.difference_minutes ? <div><span className="font-semibold">Difference:</span> {conflict.difference_minutes} minutes</div> : null}</div>
                {conflict.status === "open" ? <><textarea className="field mt-3 min-h-20" placeholder="Explain how this difference should be understood…" value={notes[conflict.id] ?? ""} onChange={(e) => setNotes((current) => ({ ...current, [conflict.id]: e.target.value }))} /><div className="mt-2 flex flex-wrap gap-2"><button disabled={busy} className="secondary-button px-3 py-2 text-xs" onClick={() => resolve(conflict, "explained")}>Explain</button><button disabled={busy} className="secondary-button px-3 py-2 text-xs" onClick={() => resolve(conflict, "accepted_difference")}>Accept difference</button><button disabled={busy} className="secondary-button px-3 py-2 text-xs" onClick={() => resolve(conflict, "resolved")}>Resolve</button><button disabled={busy} className="secondary-button px-3 py-2 text-xs" onClick={() => resolve(conflict, "irrelevant")}>Mark irrelevant</button></div></> : <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600"><span className="font-semibold">Resolution note:</span> {conflict.resolution_note ?? "—"}</div>}
              </div>)}</div> : <div className="mt-5 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">No active evidence conflicts.</div>}
          </section>
        </aside>
      </div>
    </div>
  );
}
