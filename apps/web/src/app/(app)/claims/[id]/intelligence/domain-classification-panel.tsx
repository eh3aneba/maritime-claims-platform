"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type DomainComponent = { code: string; title: string };
type DomainIncident = {
  code: string;
  title: string;
  description: string;
  component_codes: string[];
  contextual_rule_ids: string[];
};
type DomainCatalog = {
  catalog_version: string;
  non_authoritative: boolean;
  human_classification_required: boolean;
  automatic_claim_decision: boolean;
  incidents: DomainIncident[];
  machinery_components: DomainComponent[];
};
type DomainClassification = {
  id: string;
  claim_id: string;
  catalog_version: string;
  classification_number: number;
  incident_code: string;
  component_code: string | null;
  failure_mode: string | null;
  classification_note: string;
  classified_by_id: string | null;
  supersedes_classification_id: string | null;
  previous_classification_hash: string | null;
  classification_hash: string;
  created_at: string;
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function readable(code: string | null | undefined) {
  if (!code) return "—";
  return code.replaceAll("_", " ").replace(/\b\w/g, (value) => value.toUpperCase());
}

export default function DomainClassificationPanel({ claimId }: { claimId: string }) {
  const [catalog, setCatalog] = useState<DomainCatalog | null>(null);
  const [current, setCurrent] = useState<DomainClassification | null>(null);
  const [history, setHistory] = useState<DomainClassification[]>([]);
  const [incidentCode, setIncidentCode] = useState("");
  const [componentCode, setComponentCode] = useState("");
  const [failureMode, setFailureMode] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [catalogPayload, currentPayload, historyPayload] = await Promise.all([
        request<DomainCatalog>(`/claims/${claimId}/intelligence/domain-catalog`),
        request<DomainClassification | null>(`/claims/${claimId}/intelligence/domain-classification`),
        request<DomainClassification[]>(`/claims/${claimId}/intelligence/domain-classifications`),
      ]);
      setCatalog(catalogPayload);
      setCurrent(currentPayload);
      setHistory(historyPayload);
      const initialIncident = currentPayload?.incident_code ?? catalogPayload.incidents[0]?.code ?? "";
      const initialComponent = currentPayload?.component_code ?? "";
      setIncidentCode(initialIncident);
      setComponentCode(initialComponent);
      setFailureMode(currentPayload?.failure_mode ?? "");
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Claim domain classification could not be loaded.");
    }
  }, [claimId]);

  useEffect(() => { void load(); }, [load]);

  const selectedIncident = useMemo(
    () => catalog?.incidents.find((row) => row.code === incidentCode) ?? null,
    [catalog, incidentCode],
  );
  const componentByCode = useMemo(
    () => new Map((catalog?.machinery_components ?? []).map((row) => [row.code, row])),
    [catalog],
  );
  const allowedComponents = useMemo(
    () => (selectedIncident?.component_codes ?? []).map((code) => componentByCode.get(code)).filter(Boolean) as DomainComponent[],
    [selectedIncident, componentByCode],
  );
  const incidentByCode = useMemo(
    () => new Map((catalog?.incidents ?? []).map((row) => [row.code, row])),
    [catalog],
  );

  function changeIncident(value: string) {
    const nextIncident = catalog?.incidents.find((row) => row.code === value) ?? null;
    setIncidentCode(value);
    if (!nextIncident?.component_codes.includes(componentCode)) {
      setComponentCode("");
      setFailureMode("");
    }
    setMessage("");
  }

  function changeComponent(value: string) {
    setComponentCode(value);
    if (!value) setFailureMode("");
    setMessage("");
  }

  async function saveClassification() {
    if (!catalog || !incidentCode) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await request<DomainClassification>(`/claims/${claimId}/intelligence/domain-classification`, {
        method: "POST",
        body: JSON.stringify({
          incident_code: incidentCode,
          component_code: componentCode || null,
          failure_mode: failureMode.trim() || null,
          note: note.trim(),
          confirm_classification: confirmed,
        }),
      });
      const historyPayload = await request<DomainClassification[]>(`/claims/${claimId}/intelligence/domain-classifications`);
      setCurrent(saved);
      setHistory(historyPayload);
      setIncidentCode(saved.incident_code);
      setComponentCode(saved.component_code ?? "");
      setFailureMode(saved.failure_mode ?? "");
      setNote("");
      setConfirmed(false);
      setMessage(
        `Classification v${saved.classification_number} saved. Claims Intelligence was not rebuilt automatically; use Build/Refresh Intelligence when you want the new context reflected in a snapshot.`,
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Claim domain classification could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const currentIncident = current ? incidentByCode.get(current.incident_code) : null;
  const currentComponent = current?.component_code ? componentByCode.get(current.component_code) : null;

  return <section aria-label="Claim domain classification" className="panel p-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Phase 16.1 · Governed context</p>
        <h2 className="mt-2 section-title">Claim domain classification</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">
          Human-confirmed incident context only. Saving or changing this classification does not build Claims Intelligence, execute rules, create tasks, or decide coverage, causation, fault, liability, recoverability, reserve or settlement.
        </p>
      </div>
      {catalog ? <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">Catalog {catalog.catalog_version}</span> : null}
    </div>

    {error ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : null}
    {message ? <div role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800">{message}</div> : null}

    <div className="mt-5 grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p className="metric-label">Current human classification</p>
        {current ? <>
          <p className="mt-2 text-xl font-semibold text-slate-950">{currentIncident?.title ?? readable(current.incident_code)}</p>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-xs font-semibold uppercase text-slate-500">Sequence</dt><dd className="mt-1">v{current.classification_number}</dd></div>
            <div><dt className="text-xs font-semibold uppercase text-slate-500">Component</dt><dd className="mt-1">{currentComponent?.title ?? readable(current.component_code)}</dd></div>
            <div><dt className="text-xs font-semibold uppercase text-slate-500">Failure mode</dt><dd className="mt-1">{current.failure_mode ?? "—"}</dd></div>
            <div><dt className="text-xs font-semibold uppercase text-slate-500">Recorded</dt><dd className="mt-1">{new Date(current.created_at).toLocaleString()}</dd></div>
          </dl>
          <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700">
            <strong>Handler note:</strong> {current.classification_note}
          </div>
          <details className="mt-3 text-xs text-slate-600">
            <summary className="cursor-pointer font-semibold">Classification lineage</summary>
            <div className="mt-2 space-y-1 break-all font-mono text-[10px]">
              <p>ID: {current.id}</p>
              <p>Classifier: {current.classified_by_id ?? "—"}</p>
              <p>Supersedes: {current.supersedes_classification_id ?? "—"}</p>
              <p>Previous SHA-256: {current.previous_classification_hash ?? "—"}</p>
              <p>Classification SHA-256: {current.classification_hash}</p>
            </div>
          </details>
        </> : <p className="mt-2 text-sm leading-6 text-slate-600">No claim-domain classification has been recorded. Choose the incident context and confirm it below; no default classification is inferred.</p>}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-base font-semibold text-slate-950">{current ? "Record a new classification version" : "Record the first classification"}</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-medium text-slate-700">
            Incident domain
            <select aria-label="Claim incident domain" value={incidentCode} onChange={(event) => changeIncident(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">
              {(catalog?.incidents ?? []).map((row) => <option key={row.code} value={row.code}>{row.title}</option>)}
            </select>
          </label>
          {allowedComponents.length ? <label className="text-sm font-medium text-slate-700">
            Machinery component
            <select aria-label="Machinery component" value={componentCode} onChange={(event) => changeComponent(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">
              <option value="">No component selected</option>
              {allowedComponents.map((row) => <option key={row.code} value={row.code}>{row.title}</option>)}
            </select>
          </label> : <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">This incident domain has no machinery-component classification.</div>}
        </div>

        {selectedIncident ? <p className="mt-3 text-xs leading-5 text-slate-500">{selectedIncident.description}</p> : null}

        <label className="mt-4 block text-sm font-medium text-slate-700">
          Failure mode <span className="font-normal text-slate-400">(optional)</span>
          <input aria-label="Failure mode" value={failureMode} onChange={(event) => setFailureMode(event.target.value)} disabled={!componentCode} placeholder={componentCode ? "e.g. bearing damage" : "Select a machinery component first"} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 disabled:bg-slate-100" />
        </label>

        <label className="mt-4 block text-sm font-medium text-slate-700">
          Human classification note
          <textarea aria-label="Human classification note" value={note} onChange={(event) => setNote(event.target.value)} rows={3} maxLength={2000} placeholder="State the evidence/review basis for this classification (minimum 20 characters)." className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
        </label>

        <label className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-5 text-amber-950">
          <input aria-label="Confirm claim domain classification" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" />
          <span>I confirm this is a human classification of incident context only and not a coverage, causation, fault, liability, recoverability or settlement decision.</span>
        </label>

        <button type="button" disabled={busy || !catalog || !incidentCode || note.trim().length < 20 || !confirmed} onClick={() => void saveClassification()} className="primary-button mt-4 disabled:opacity-40">
          {busy ? "Saving classification…" : current ? "Save new classification version" : "Save classification"}
        </button>
      </div>
    </div>

    <details className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-800">Classification history · {history.length} version{history.length === 1 ? "" : "s"}</summary>
      <div className="mt-4 space-y-3">
        {history.length ? history.map((row) => <article key={row.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong>v{row.classification_number} · {incidentByCode.get(row.incident_code)?.title ?? readable(row.incident_code)}</strong>
            <span className="text-xs text-slate-500">{new Date(row.created_at).toLocaleString()}</span>
          </div>
          <p className="mt-2 text-slate-600">Component: {componentByCode.get(row.component_code ?? "")?.title ?? readable(row.component_code)} · Failure mode: {row.failure_mode ?? "—"}</p>
          <p className="mt-2 leading-6 text-slate-700"><strong>Note:</strong> {row.classification_note}</p>
          <p className="mt-2 break-all font-mono text-[10px] text-slate-500">SHA-256: {row.classification_hash}</p>
        </article>) : <p className="text-sm text-slate-500">No historical classification versions yet.</p>}
      </div>
    </details>
  </section>;
}
