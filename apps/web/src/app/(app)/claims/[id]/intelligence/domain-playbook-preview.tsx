"use client";

import { useCallback, useEffect, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type PlaybookSourceRef = {
  kind: "claim_domain_classification";
  id: string;
  catalog_version: string;
  classification_number: number;
  classification_hash: string;
};

type PlaybookClassificationContext = {
  incident_code: string;
  incident_title: string;
  component_code: string | null;
  component_title: string | null;
  failure_mode: string | null;
};

type PlaybookDefinition = {
  incident_code: string;
  title: string;
  objective: string;
  investigation_tracks: string[];
  evidence_prompts: string[];
  review_topics: string[];
  contextual_rule_ids: string[];
};

type PlaybookPreview = {
  registry_version: string;
  registry_hash: string;
  classification_required: boolean;
  non_authoritative: boolean;
  read_only_preview: boolean;
  automatic_rule_execution: boolean;
  automatic_requirement_activation: boolean;
  automatic_task_creation: boolean;
  automatic_claim_decision: boolean;
  authority_boundary: string;
  source_ref: PlaybookSourceRef | null;
  classification_context: PlaybookClassificationContext | null;
  playbook: PlaybookDefinition | null;
};

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
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

function PromptList({ items }: { items: string[] }) {
  return (
    <ul className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
      {items.map((item, index) => (
        <li key={`${index}-${item}`} className="flex gap-2">
          <span aria-hidden="true" className="mt-[0.55rem] h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-600" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function DomainPlaybookPreview({ claimId }: { claimId: string }) {
  const [preview, setPreview] = useState<PlaybookPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await request<PlaybookPreview>(`/claims/${claimId}/intelligence/domain-playbook-preview`);
      setPreview(payload);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Domain investigation playbook preview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [claimId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    function handleClassificationUpdated(event: Event) {
      const detail = (event as CustomEvent<{ claimId?: string }>).detail;
      if (detail?.claimId === claimId) void load();
    }
    window.addEventListener("claim-domain-classification-updated", handleClassificationUpdated);
    return () => window.removeEventListener("claim-domain-classification-updated", handleClassificationUpdated);
  }, [claimId, load]);

  return (
    <section aria-label="Domain investigation playbook" className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Phase 16.2 · Read-only preview</p>
          <h2 className="mt-2 section-title">Domain investigation playbook</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">
            Investigation prompts derived from the latest human-confirmed claim domain. This preview does not execute rules, activate evidence requirements, create tasks, build Claims Intelligence, or make a substantive claim decision.
          </p>
        </div>
        {preview ? (
          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
            Registry {preview.registry_version}
          </span>
        ) : null}
      </div>

      {error ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : null}
      {loading && !preview ? <p className="mt-4 text-sm text-slate-500">Loading governed playbook preview…</p> : null}

      {preview?.classification_required ? (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          <strong>Human classification required.</strong> Record a claim-domain classification above before a domain-specific playbook can be shown. No incident type or investigation plan is inferred automatically.
        </div>
      ) : null}

      {preview?.playbook && preview.classification_context && preview.source_ref ? (
        <div className="mt-5 space-y-5">
          <div className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-cyan-800">Current playbook context</p>
                <h3 className="mt-1 text-xl font-semibold text-slate-950">{preview.playbook.title}</h3>
              </div>
              <span className="rounded-full border border-cyan-200 bg-white px-3 py-1 text-xs font-semibold text-cyan-900">
                Classification v{preview.source_ref.classification_number}
              </span>
            </div>
            <p className="mt-3 text-sm leading-6 text-slate-700">{preview.playbook.objective}</p>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Incident</dt><dd className="mt-1">{preview.classification_context.incident_title}</dd></div>
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Component</dt><dd className="mt-1">{preview.classification_context.component_title ?? "—"}</dd></div>
              <div><dt className="text-xs font-semibold uppercase text-slate-500">Failure mode</dt><dd className="mt-1">{preview.classification_context.failure_mode ?? "—"}</dd></div>
            </dl>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <article className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="text-base font-semibold text-slate-950">Investigation tracks</h3>
              <PromptList items={preview.playbook.investigation_tracks} />
            </article>
            <article className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="text-base font-semibold text-slate-950">Evidence prompts</h3>
              <PromptList items={preview.playbook.evidence_prompts} />
            </article>
            <article className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="text-base font-semibold text-slate-950">Review topics</h3>
              <PromptList items={preview.playbook.review_topics} />
            </article>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-semibold text-slate-900">Contextual Marine Registry references</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              References only — these rules have not been evaluated or triggered by this playbook preview.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {preview.playbook.contextual_rule_ids.length ? preview.playbook.contextual_rule_ids.map((ruleId) => (
                <span key={ruleId} className="rounded-full border border-slate-300 bg-white px-3 py-1 font-mono text-xs text-slate-700">{ruleId}</span>
              )) : <span className="text-sm text-slate-500">No contextual registry references are defined for this playbook.</span>}
            </div>
          </div>

          <details className="rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-600">
            <summary className="cursor-pointer font-semibold">Playbook source lineage</summary>
            <div className="mt-3 space-y-1 break-all font-mono text-[10px]">
              <p>Classification ID: {preview.source_ref.id}</p>
              <p>Classification catalog: {preview.source_ref.catalog_version}</p>
              <p>Classification sequence: v{preview.source_ref.classification_number}</p>
              <p>Classification SHA-256: {preview.source_ref.classification_hash}</p>
              <p>Playbook registry: {preview.registry_version}</p>
              <p>Registry SHA-256: {preview.registry_hash}</p>
            </div>
          </details>

          <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600">
            {preview.authority_boundary}
          </p>
        </div>
      ) : null}
    </section>
  );
}
