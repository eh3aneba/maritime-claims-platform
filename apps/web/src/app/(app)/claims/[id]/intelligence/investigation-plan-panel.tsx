"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type PlaybookPreview = {
  registry_version: string;
  registry_hash: string;
  classification_required: boolean;
  source_ref: {
    id: string;
    catalog_version: string;
    classification_number: number;
    classification_hash: string;
  } | null;
  classification_context: {
    incident_code: string;
    incident_title: string;
    component_code: string | null;
    component_title: string | null;
    failure_mode: string | null;
  } | null;
  playbook: {
    incident_code: string;
    title: string;
    objective: string;
    investigation_tracks: string[];
    evidence_prompts: string[];
    review_topics: string[];
    contextual_rule_ids: string[];
  } | null;
};

type InvestigationPlan = {
  id: string;
  claim_id: string;
  plan_number: number;
  classification_id: string;
  catalog_version: string;
  classification_number: number;
  classification_hash: string;
  registry_version: string;
  registry_hash: string;
  incident_code: string;
  component_code: string | null;
  failure_mode: string | null;
  investigation_tracks: string[];
  evidence_prompts: string[];
  review_topics: string[];
  contextual_rule_ids: string[];
  adoption_note: string;
  adopted_by_id: string | null;
  supersedes_plan_id: string | null;
  previous_plan_hash: string | null;
  adoption_key_hash: string;
  plan_hash: string;
  adopted_at: string;
  source_current: boolean;
  non_authoritative: boolean;
  automatic_rule_execution: boolean;
  automatic_requirement_activation: boolean;
  automatic_task_creation: boolean;
  automatic_claim_decision: boolean;
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

function SelectionGroup({
  title,
  items,
  selected,
  onToggle,
}: {
  title: string;
  items: string[];
  selected: string[];
  onToggle: (item: string, checked: boolean) => void;
}) {
  return (
    <fieldset className="rounded-xl border border-slate-200 bg-white p-4">
      <legend className="px-1 text-sm font-semibold text-slate-900">{title}</legend>
      <div className="mt-2 space-y-3">
        {items.map((item, index) => (
          <label key={`${title}-${index}-${item}`} className="flex items-start gap-3 text-sm leading-6 text-slate-700">
            <input
              type="checkbox"
              checked={selected.includes(item)}
              onChange={(event) => onToggle(item, event.target.checked)}
              className="mt-1"
              aria-label={`${title}: ${item}`}
            />
            <span>{item}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export default function InvestigationPlanPanel({ claimId }: { claimId: string }) {
  const [preview, setPreview] = useState<PlaybookPreview | null>(null);
  const [current, setCurrent] = useState<InvestigationPlan | null>(null);
  const [history, setHistory] = useState<InvestigationPlan[]>([]);
  const [tracks, setTracks] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<string[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [previewPayload, currentPayload, historyPayload] = await Promise.all([
        request<PlaybookPreview>(`/claims/${claimId}/intelligence/domain-playbook-preview`),
        request<InvestigationPlan | null>(`/claims/${claimId}/intelligence/investigation-plan`),
        request<InvestigationPlan[]>(`/claims/${claimId}/intelligence/investigation-plans`),
      ]);
      setPreview(previewPayload);
      setCurrent(currentPayload);
      setHistory(historyPayload);
      setTracks([]);
      setEvidence([]);
      setTopics([]);
      setConfirmed(false);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Investigation plan workspace could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [claimId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    function handleClassificationUpdated(event: Event) {
      const detail = (event as CustomEvent<{ claimId?: string }>).detail;
      if (detail?.claimId === claimId) {
        setMessage("");
        void load();
      }
    }
    window.addEventListener("claim-domain-classification-updated", handleClassificationUpdated);
    return () => window.removeEventListener("claim-domain-classification-updated", handleClassificationUpdated);
  }, [claimId, load]);

  const selectedCount = tracks.length + evidence.length + topics.length;
  const canAdopt = Boolean(
    preview?.source_ref && preview.playbook && selectedCount > 0 && note.trim().length >= 20 && confirmed && !busy,
  );

  const sourceStatus = useMemo(() => {
    if (!current) return null;
    return current.source_current ? "Current source" : "Stale source — explicit re-adoption required";
  }, [current]);

  function toggle(setter: React.Dispatch<React.SetStateAction<string[]>>, item: string, checked: boolean) {
    setter((existing) => checked ? [...existing, item] : existing.filter((value) => value !== item));
    setMessage("");
  }

  async function adoptPlan() {
    if (!preview?.source_ref || !preview.playbook) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await request<InvestigationPlan>(`/claims/${claimId}/intelligence/investigation-plan`, {
        method: "POST",
        body: JSON.stringify({
          registry_version: preview.registry_version,
          registry_hash: preview.registry_hash,
          classification_id: preview.source_ref.id,
          classification_hash: preview.source_ref.classification_hash,
          investigation_tracks: tracks,
          evidence_prompts: evidence,
          review_topics: topics,
          note: note.trim(),
          confirm_adoption: confirmed,
        }),
      });
      const historyPayload = await request<InvestigationPlan[]>(`/claims/${claimId}/intelligence/investigation-plans`);
      setCurrent(saved);
      setHistory(historyPayload);
      setTracks([]);
      setEvidence([]);
      setTopics([]);
      setNote("");
      setConfirmed(false);
      setMessage(
        `Investigation plan v${saved.plan_number} adopted. No rules were executed and no requirements, tasks or Claims Intelligence snapshots were created automatically.`,
      );
      window.dispatchEvent(new CustomEvent("claim-investigation-plan-updated", { detail: { claimId } }));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Investigation plan could not be adopted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Governed investigation plan" className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Phase 16.2 · Human adoption</p>
          <h2 className="mt-2 section-title">Governed investigation plan</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">
            Select canonical prompts from the live domain playbook and explicitly adopt them as an immutable human investigation plan. Adoption does not execute rules, request documents, create tasks, build Claims Intelligence, or decide any substantive claim issue.
          </p>
        </div>
        {current ? (
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${current.source_current ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
            Plan v{current.plan_number} · {sourceStatus}
          </span>
        ) : null}
      </div>

      {error ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : null}
      {message ? <div role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800">{message}</div> : null}
      {loading && !preview ? <p className="mt-4 text-sm text-slate-500">Loading investigation plan workspace…</p> : null}

      {preview?.classification_required ? (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          <strong>Human classification required.</strong> No investigation plan can be adopted until a claim-domain classification exists. No default plan is inferred.
        </div>
      ) : null}

      {current ? (
        <div className={`mt-5 rounded-xl border p-4 ${current.source_current ? "border-emerald-200 bg-emerald-50/50" : "border-amber-200 bg-amber-50/60"}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-600">Current adopted plan</p>
              <h3 className="mt-1 text-lg font-semibold text-slate-950">Plan v{current.plan_number} · {current.incident_code.replaceAll("_", " ")}</h3>
            </div>
            <strong className="text-xs text-slate-700">{sourceStatus}</strong>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <div><p className="metric-label">Investigation tracks</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{current.investigation_tracks.map((item) => <li key={item}>{item}</li>)}</ul></div>
            <div><p className="metric-label">Evidence prompts</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{current.evidence_prompts.map((item) => <li key={item}>{item}</li>)}</ul></div>
            <div><p className="metric-label">Review topics</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{current.review_topics.map((item) => <li key={item}>{item}</li>)}</ul></div>
          </div>
          <p className="mt-4 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-700"><strong>Adoption note:</strong> {current.adoption_note}</p>
          <details className="mt-3 text-xs text-slate-600">
            <summary className="cursor-pointer font-semibold">Investigation plan lineage</summary>
            <div className="mt-2 space-y-1 break-all font-mono text-[10px]">
              <p>Plan ID: {current.id}</p>
              <p>Classification ID: {current.classification_id}</p>
              <p>Classification SHA-256: {current.classification_hash}</p>
              <p>Registry: {current.registry_version}</p>
              <p>Registry SHA-256: {current.registry_hash}</p>
              <p>Supersedes: {current.supersedes_plan_id ?? "—"}</p>
              <p>Previous plan SHA-256: {current.previous_plan_hash ?? "—"}</p>
              <p>Adoption key SHA-256: {current.adoption_key_hash}</p>
              <p>Plan SHA-256: {current.plan_hash}</p>
            </div>
          </details>
        </div>
      ) : preview && !preview.classification_required ? (
        <p className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">No investigation plan has been adopted for this claim yet.</p>
      ) : null}

      {preview?.playbook && preview.source_ref ? (
        <div className="mt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-slate-950">Adopt from current playbook</h3>
              <p className="mt-1 text-xs text-slate-500">Source: classification v{preview.source_ref.classification_number} · registry {preview.registry_version}. Choose at least one item.</p>
            </div>
            <span className="text-xs font-semibold text-slate-600">{selectedCount} selected</span>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <SelectionGroup title="Investigation tracks" items={preview.playbook.investigation_tracks} selected={tracks} onToggle={(item, checked) => toggle(setTracks, item, checked)} />
            <SelectionGroup title="Evidence prompts" items={preview.playbook.evidence_prompts} selected={evidence} onToggle={(item, checked) => toggle(setEvidence, item, checked)} />
            <SelectionGroup title="Review topics" items={preview.playbook.review_topics} selected={topics} onToggle={(item, checked) => toggle(setTopics, item, checked)} />
          </div>

          <label className="mt-4 block text-sm font-medium text-slate-700">
            Human adoption note
            <textarea aria-label="Investigation plan adoption note" value={note} onChange={(event) => setNote(event.target.value)} rows={3} maxLength={2000} placeholder="State why this bounded selection is being adopted (minimum 20 characters)." className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>

          <label className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-5 text-amber-950">
            <input aria-label="Confirm investigation plan adoption" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" />
            <span>I confirm this is a human investigation plan only. It does not activate rules, request documents, create tasks, determine coverage/liability, or change Claims Intelligence automatically.</span>
          </label>

          <button type="button" disabled={!canAdopt} onClick={() => void adoptPlan()} className="primary-button mt-4 disabled:opacity-40">
            {busy ? "Adopting investigation plan…" : current ? "Adopt new investigation plan version" : "Adopt investigation plan"}
          </button>
        </div>
      ) : null}

      <details className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">Investigation plan history · {history.length} version{history.length === 1 ? "" : "s"}</summary>
        <div className="mt-4 space-y-3">
          {history.length ? history.map((row) => (
            <article key={row.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong>v{row.plan_number} · {row.incident_code.replaceAll("_", " ")}</strong>
                <span className="text-xs text-slate-500">{new Date(row.adopted_at).toLocaleString()} · {row.source_current ? "current source" : "stale source"}</span>
              </div>
              <p className="mt-2 text-slate-600">{row.investigation_tracks.length} tracks · {row.evidence_prompts.length} evidence prompts · {row.review_topics.length} review topics</p>
              <p className="mt-2 leading-6 text-slate-700"><strong>Note:</strong> {row.adoption_note}</p>
              <p className="mt-2 break-all font-mono text-[10px] text-slate-500">SHA-256: {row.plan_hash}</p>
            </article>
          )) : <p className="text-sm text-slate-500">No investigation plan versions yet.</p>}
        </div>
      </details>
    </section>
  );
}
