"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError, attestAIDocumentEligibility, createAIProviderActivation,
  decideAIProviderActivation, getAIGovernance, reviewAIProviderActivation,
  revokeAIDocumentEligibility, revokeAIProviderActivation,
} from "@/lib/api";
import type {
  AIDocumentEligibility, AIGovernanceDashboard, AIProviderActivation,
} from "@/lib/types";

const approvalRoles = ["security", "privacy", "product"] as const;

function statusStyle(status: string) {
  if (["staging_authorized", "decision_ready", "eligible"].includes(status)) {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }
  if (["rejected", "held", "revoked"].includes(status)) {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function Badge({ value }: { value: string }) {
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${statusStyle(value)}`}>{value.replaceAll("_", " ")}</span>;
}

export default function AIGovernancePage() {
  const [data, setData] = useState<AIGovernanceDashboard | null>(null);
  const [model, setModel] = useState("");
  const [claimId, setClaimId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [dataMode, setDataMode] = useState<"synthetic" | "deidentified">("synthetic");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getAIGovernance());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load AI governance.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const latest = data?.activation_requests[0] ?? null;
  const canCreate = !latest || ["rejected", "held", "revoked"].includes(latest.status)
    || (latest.status === "staging_authorized"
      && new Date(latest.evaluation_expires_at).getTime() <= Date.now());
  const active = useMemo(
    () => data?.activation_requests.find((item) => item.summary.authorization_active) ?? null,
    [data],
  );

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try {
      await action();
      setMessage(success);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "The governance action failed.");
    } finally {
      setBusy(null);
    }
  }

  async function createRequest(event: FormEvent) {
    event.preventDefault();
    const pinnedModel = model.trim();
    if (!pinnedModel) { setError("Enter the exact model configured in staging."); return; }
    await run("create", () => createAIProviderActivation(pinnedModel),
      "A bounded staging activation request was created. No provider settings or keys were changed.");
  }

  async function attestDocument(event: FormEvent) {
    event.preventDefault();
    if (!active) { setError("An active staging authorization is required first."); return; }
    await run("attest-document", () => attestAIDocumentEligibility({
      activation_request_id: active.id, claim_id: claimId.trim(),
      document_id: documentId.trim(), data_mode: dataMode,
    }), "Document eligibility was attested for this staging authorization.");
    setClaimId(""); setDocumentId("");
  }

  return (
    <div className="space-y-7">
      <section className="overflow-hidden rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
        <div className="max-w-4xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11A · external AI gate</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">AI provider activation</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
            This control plane records a bounded OpenAI staging evaluation. It does not store a key,
            change provider configuration, authorize production or restricted/real claim data, or bypass human review.
          </p>
        </div>
      </section>

      {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

      <section className="grid gap-4 md:grid-cols-4">
        {[
          ["Requests", data?.activation_requests.length ?? 0],
          ["Current approvals", latest?.summary.approval_count ?? 0],
          ["Active authorization", active ? "Yes" : "No"],
          ["Eligible documents", data?.document_eligibility.filter((item) => item.status === "eligible").length ?? 0],
        ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p></div>)}
      </section>

      {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">Create a staging evaluation request</h2>
        <p className="mt-2 text-sm text-slate-600">Use the exact model identifier separately configured in the staging secret-controlled environment.</p>
        <form onSubmit={createRequest} className="mt-5 flex max-w-2xl flex-col gap-3 sm:flex-row">
          <label className="sr-only" htmlFor="model">Pinned OpenAI model</label>
          <input id="model" value={model} onChange={(event) => setModel(event.target.value)} placeholder="Pinned OpenAI model" className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100" />
          <button disabled={busy !== null} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Create bounded request</button>
        </form>
      </section>}

      {latest && <ActivationCard item={latest} busy={busy} run={run} />}

      <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold">Document eligibility</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">Only a synthetic or independently de-identified, non-restricted document can be attached to the current authorization.</p>
          <form onSubmit={attestDocument} className="mt-5 space-y-3">
            <input value={claimId} onChange={(event) => setClaimId(event.target.value)} required placeholder="Claim UUID" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input value={documentId} onChange={(event) => setDocumentId(event.target.value)} required placeholder="Document UUID" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <select value={dataMode} onChange={(event) => setDataMode(event.target.value as "synthetic" | "deidentified")} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="synthetic">Synthetic</option><option value="deidentified">De-identified</option>
            </select>
            <button disabled={!active || busy !== null} className="w-full rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Attest eligibility</button>
          </form>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold">Eligibility ledger</h2>
          <div className="mt-4 space-y-3">
            {data?.document_eligibility.length ? data.document_eligibility.map((item) => <EligibilityRow key={item.id} item={item} busy={busy} run={run} />) : <p className="text-sm text-slate-500">No document attestations recorded.</p>}
          </div>
        </div>
      </section>
    </div>
  );
}

function ActivationCard({ item, busy, run }: {
  item: AIProviderActivation; busy: string | null;
  run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const approvalByRole = new Map(item.approvals.map((approval) => [approval.approval_role, approval]));
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {item.attempt_number} · {item.provider_project_label}</p><h2 className="mt-1 text-xl font-semibold">{item.model}</h2><p className="mt-1 text-sm text-slate-500">Expires {new Date(item.evaluation_expires_at).toLocaleString()}</p></div>
      <Badge value={item.status} />
    </div>
    <div className="mt-5 grid gap-3 md:grid-cols-3">
      {approvalRoles.map((role) => {
        const approval = approvalByRole.get(role);
        return <div key={role} className="rounded-xl border border-slate-200 p-4">
          <div className="flex items-center justify-between"><p className="font-semibold capitalize">{role}</p>{approval && <Badge value={approval.action} />}</div>
          {approval ? <p className="mt-3 text-xs leading-5 text-slate-500">Recorded by an independent reviewer.</p> : <div className="mt-3 flex gap-2"><button disabled={busy !== null || !["pending_approvals", "decision_ready"].includes(item.status)} onClick={() => void run(`approve-${role}`, () => reviewAIProviderActivation(item.id, role, "approve"), `${role} review recorded.`)} className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Approve</button><button disabled={busy !== null || !["pending_approvals", "decision_ready"].includes(item.status)} onClick={() => void run(`reject-${role}`, () => reviewAIProviderActivation(item.id, role, "reject"), `${role} rejection recorded.`)} className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-40">Reject</button></div>}
        </div>;
      })}
    </div>
    <p className="mt-3 text-xs text-slate-500">The requester and the three approvers must be four distinct users. Switch accounts between reviews.</p>
    <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("authorize", () => decideAIProviderActivation(item.id, "authorize_staging"), "Staging evaluation authorized; runtime still requires eligible documents and matching configuration.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Authorize staging</button>
      <button disabled={busy !== null || item.status !== "decision_ready"} onClick={() => void run("hold", () => decideAIProviderActivation(item.id, "hold"), "Activation attempt placed on hold.")} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-40">Hold</button>
      <button disabled={busy !== null || item.status !== "staging_authorized"} onClick={() => void run("revoke", () => revokeAIProviderActivation(item.id), "AI application kill switch activated.")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Revoke / kill switch</button>
    </div>
  </section>;
}

function EligibilityRow({ item, busy, run }: {
  item: AIDocumentEligibility; busy: string | null;
  run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  return <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4">
    <div className="min-w-0"><div className="flex items-center gap-2"><p className="font-medium">{item.document_type.replaceAll("_", " ")}</p><Badge value={item.status} /></div><p className="mt-1 truncate text-xs text-slate-500">{item.document_id} · {item.data_mode} · SHA-256 {item.snapshot_hash.slice(0, 12)}…</p></div>
    <button disabled={busy !== null || item.status !== "eligible"} onClick={() => void run(`revoke-document-${item.id}`, () => revokeAIDocumentEligibility(item.id), "Document eligibility revoked.")} className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-40">Revoke</button>
  </div>;
}
