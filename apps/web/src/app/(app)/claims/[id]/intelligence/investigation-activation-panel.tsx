"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type InvestigationPlan = {
  id: string;
  plan_number: number;
  plan_hash: string;
  investigation_tracks: string[];
  evidence_prompts: string[];
  review_topics: string[];
  source_current: boolean;
};

type ActivationWorkItem = {
  key: string;
  kind: string;
  text: string;
  task_id: string | null;
  task_title: string | null;
  task_status: string | null;
  task_type: string | null;
};

type InvestigationActivation = {
  id: string;
  claim_id: string;
  activation_number: number;
  plan_id: string;
  plan_number: number;
  plan_hash: string;
  selected_items: Array<{ key: string; kind: string; text: string }>;
  activation_note: string;
  activated_by_id: string | null;
  assignee_id: string | null;
  due_date: string | null;
  previous_activation_hash: string | null;
  activation_key_hash: string;
  activation_hash: string;
  activated_at: string;
  plan_current: boolean;
  work_items: ActivationWorkItem[];
  automatic_rule_execution: boolean;
  automatic_requirement_activation: boolean;
  automatic_document_request: boolean;
  automatic_intelligence_build: boolean;
  automatic_claim_decision: boolean;
};

type PlanItem = { key: string; kind: string; text: string };

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

export default function InvestigationActivationPanel({ claimId }: { claimId: string }) {
  const [plan, setPlan] = useState<InvestigationPlan | null>(null);
  const [current, setCurrent] = useState<InvestigationActivation | null>(null);
  const [history, setHistory] = useState<InvestigationActivation[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [planPayload, currentPayload, historyPayload] = await Promise.all([
        request<InvestigationPlan | null>(`/claims/${claimId}/intelligence/investigation-plan`),
        request<InvestigationActivation | null>(`/claims/${claimId}/intelligence/investigation-plan-activation`),
        request<InvestigationActivation[]>(`/claims/${claimId}/intelligence/investigation-plan-activations`),
      ]);
      setPlan(planPayload);
      setCurrent(currentPayload);
      setHistory(historyPayload);
      setSelected([]);
      setConfirmed(false);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Investigation activation workspace could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [claimId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    const refresh = (event: Event) => {
      const detail = (event as CustomEvent<{ claimId?: string }>).detail;
      if (detail?.claimId === claimId) {
        setMessage("");
        void load();
      }
    };
    window.addEventListener("claim-investigation-plan-updated", refresh);
    window.addEventListener("claim-domain-classification-updated", refresh);
    return () => {
      window.removeEventListener("claim-investigation-plan-updated", refresh);
      window.removeEventListener("claim-domain-classification-updated", refresh);
    };
  }, [claimId, load]);

  const items = useMemo<PlanItem[]>(() => {
    if (!plan) return [];
    return [
      ...plan.investigation_tracks.map((text, index) => ({ key: `track:${index}`, kind: "Investigation track", text })),
      ...plan.evidence_prompts.map((text, index) => ({ key: `evidence:${index}`, kind: "Evidence follow-up", text })),
      ...plan.review_topics.map((text, index) => ({ key: `review:${index}`, kind: "Review topic", text })),
    ];
  }, [plan]);

  const canActivate = Boolean(
    plan?.source_current && selected.length > 0 && note.trim().length >= 20 && confirmed && !busy,
  );

  function toggle(key: string, checked: boolean) {
    setSelected((existing) => checked ? [...existing, key] : existing.filter((value) => value !== key));
    setMessage("");
  }

  async function activate() {
    if (!plan) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await request<InvestigationActivation>(
        `/claims/${claimId}/intelligence/investigation-plan-activation`,
        {
          method: "POST",
          body: JSON.stringify({
            plan_id: plan.id,
            plan_hash: plan.plan_hash,
            item_keys: selected,
            due_date: dueDate || null,
            note: note.trim(),
            confirm_activation: confirmed,
          }),
        },
      );
      const historyPayload = await request<InvestigationActivation[]>(
        `/claims/${claimId}/intelligence/investigation-plan-activations`,
      );
      setCurrent(saved);
      setHistory(historyPayload);
      setSelected([]);
      setNote("");
      setDueDate("");
      setConfirmed(false);
      setMessage(
        `Activation v${saved.activation_number} created ${saved.work_items.length} human work item${saved.work_items.length === 1 ? "" : "s"}. No rules, document requests or Claims Intelligence rebuild were triggered.`,
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Investigation work items could not be activated.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Investigation plan activation" className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-700">Phase 16.2 · Human workflow activation</p>
          <h2 className="mt-2 section-title">Activate investigation work items</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">
            Convert selected items from the exact current Investigation Plan into human-owned claim tasks. This action does not run rules, create document requirements or requests, rebuild Claims Intelligence, or decide any substantive claim issue.
          </p>
        </div>
        {current ? (
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${current.plan_current ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
            Activation v{current.activation_number} · {current.plan_current ? "Current plan" : "Stale plan source"}
          </span>
        ) : null}
      </div>

      {error ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : null}
      {message ? <div role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800">{message}</div> : null}
      {loading && !plan ? <p className="mt-4 text-sm text-slate-500">Loading activation workspace…</p> : null}

      {!loading && !plan ? (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          <strong>Investigation Plan required.</strong> Adopt a governed plan before creating human work items.
        </div>
      ) : null}

      {plan && !plan.source_current ? (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          <strong>Current plan is stale.</strong> Re-adopt a plan from the live classification/playbook source before activation.
        </div>
      ) : null}

      {current ? (
        <div className={`mt-5 rounded-xl border p-4 ${current.plan_current ? "border-emerald-200 bg-emerald-50/50" : "border-amber-200 bg-amber-50/60"}`}>
          <h3 className="text-base font-semibold text-slate-950">Latest activation v{current.activation_number} · Plan v{current.plan_number}</h3>
          <div className="mt-3 space-y-2">
            {current.work_items.map((item) => (
              <div key={item.key} className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong className="text-slate-900">{item.task_title ?? item.text}</strong>
                  <span className="text-xs font-semibold uppercase text-slate-500">{item.task_status ?? "unknown"}</span>
                </div>
                <p className="mt-1 text-xs text-slate-600">{item.kind.replaceAll("_", " ")} · {item.key}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-700"><strong>Activation note:</strong> {current.activation_note}</p>
          <details className="mt-3 text-xs text-slate-600">
            <summary className="cursor-pointer font-semibold">Activation lineage</summary>
            <div className="mt-2 space-y-1 break-all font-mono text-[10px]">
              <p>Activation ID: {current.id}</p>
              <p>Plan ID: {current.plan_id}</p>
              <p>Plan SHA-256: {current.plan_hash}</p>
              <p>Previous activation SHA-256: {current.previous_activation_hash ?? "—"}</p>
              <p>Activation key SHA-256: {current.activation_key_hash}</p>
              <p>Activation SHA-256: {current.activation_hash}</p>
            </div>
          </details>
        </div>
      ) : null}

      {plan?.source_current ? (
        <div className="mt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-slate-950">Activate from Plan v{plan.plan_number}</h3>
              <p className="mt-1 text-xs text-slate-500">Select exact immutable plan items. Already-activated plan items fail closed rather than creating duplicates.</p>
            </div>
            <span className="text-xs font-semibold text-slate-600">{selected.length} selected</span>
          </div>
          <div className="mt-4 space-y-3">
            {items.map((item) => (
              <label key={item.key} className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.includes(item.key)}
                  onChange={(event) => toggle(item.key, event.target.checked)}
                  aria-label={`Activate ${item.kind}: ${item.text}`}
                />
                <span><strong>{item.kind}:</strong> {item.text}</span>
              </label>
            ))}
          </div>

          <label className="mt-4 block text-sm font-medium text-slate-700">
            Due date (optional)
            <input aria-label="Investigation activation due date" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <label className="mt-4 block text-sm font-medium text-slate-700">
            Human activation note
            <textarea aria-label="Investigation activation note" value={note} onChange={(event) => setNote(event.target.value)} rows={3} maxLength={2000} placeholder="State why these plan items should become human work items (minimum 20 characters)." className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <label className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-5 text-amber-950">
            <input aria-label="Confirm investigation work activation" type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1" />
            <span>I confirm these are human-owned work items only. This does not run rules, create document requests, rebuild Claims Intelligence, or determine coverage/liability.</span>
          </label>
          <button type="button" disabled={!canActivate} onClick={() => void activate()} className="primary-button mt-4 disabled:opacity-40">
            {busy ? "Activating human work items…" : "Activate selected work items"}
          </button>
        </div>
      ) : null}

      <details className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">Activation history · {history.length} record{history.length === 1 ? "" : "s"}</summary>
        <div className="mt-4 space-y-3">
          {history.length ? history.map((row) => (
            <article key={row.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong>Activation v{row.activation_number} · Plan v{row.plan_number}</strong>
                <span className="text-xs font-semibold text-slate-500">{row.plan_current ? "current" : "stale"}</span>
              </div>
              <p className="mt-1 text-xs text-slate-600">{row.work_items.length} human work item{row.work_items.length === 1 ? "" : "s"}</p>
            </article>
          )) : <p className="text-sm text-slate-500">No plan activation has been recorded.</p>}
        </div>
      </details>
    </section>
  );
}
