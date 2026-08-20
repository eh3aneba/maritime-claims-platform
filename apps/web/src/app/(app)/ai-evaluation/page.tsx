"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError, createAIEvaluationSuite, decideAIEvaluationPromotion,
  finalizeAIEvaluationSuite, getAIEvaluation, getAIGovernance,
  recordAIEvaluationCase, reviewAIEvaluationSuite, revokeAIEvaluationPromotion,
} from "@/lib/api";
import type { AIEvaluationDashboard, AIEvaluationSuite, AIGovernanceDashboard } from "@/lib/types";

type Scenario = "baseline" | "prompt_injection" | "malformed_input" | "cross_tenant" | "restricted_data";
type CaseDraft = {
  case_key: string; document_type: "chief_engineer_report" | "engine_log";
  scenario_type: Scenario; data_mode: "synthetic" | "deidentified"; result: "pass" | "fail";
  field_true_positive: number; field_false_positive: number; field_false_negative: number;
  extracted_claim_count: number; unsupported_claim_count: number;
  source_quote_checked_count: number; source_quote_valid_count: number;
  human_approved_count: number; human_edited_count: number; human_rejected_count: number;
  latency_ms: number; input_tokens: number; output_tokens: number;
  observed_provider_cost_microusd: number; boundary_control_passed: boolean;
  evidence_reference: string; note: string;
};

const initialCase: CaseDraft = {
  case_key: "", document_type: "chief_engineer_report", scenario_type: "baseline",
  data_mode: "synthetic", result: "pass", field_true_positive: 95,
  field_false_positive: 5, field_false_negative: 10, extracted_claim_count: 100,
  unsupported_claim_count: 1, source_quote_checked_count: 100,
  source_quote_valid_count: 99, human_approved_count: 9, human_edited_count: 1,
  human_rejected_count: 0, latency_ms: 2500, input_tokens: 1500, output_tokens: 500,
  observed_provider_cost_microusd: 150000, boundary_control_passed: true,
  evidence_reference: "artifact://ai-evaluation/observed-case-result",
  note: "Observed content-free benchmark metrics verified against the controlled evaluation artifact.",
};
const controlClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

function badge(status: string) {
  if (["review_ready", "promotion_ready", "staging_promoted", "pass"].includes(status)) {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }
  if (["failed", "review_rejected", "held", "revoked", "fail"].includes(status)) {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function Badge({ value }: { value: string }) {
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${badge(value)}`}>{value.replaceAll("_", " ")}</span>;
}

function metric(item: AIEvaluationSuite, key: string) {
  const value = item.metrics?.[key];
  return typeof value === "number" ? value : null;
}

function percent(value: number | null) {
  return value === null ? "—" : `${(value / 100).toFixed(2)}%`;
}

export default function AIEvaluationPage() {
  const [evaluation, setEvaluation] = useState<AIEvaluationDashboard | null>(null);
  const [governance, setGovernance] = useState<AIGovernanceDashboard | null>(null);
  const [draft, setDraft] = useState<CaseDraft>(initialCase);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [evaluationData, governanceData] = await Promise.all([getAIEvaluation(), getAIGovernance()]);
      setEvaluation(evaluationData); setGovernance(governanceData); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load the AI evaluation gate.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const activeActivation = governance?.activation_requests.find((item) => item.summary.authorization_active) ?? null;
  const latest = evaluation?.suites[0] ?? null;
  const canCreate = !latest || ["failed", "review_rejected", "held", "revoked"].includes(latest.status)
    || (latest.status === "staging_promoted" && latest.promotion_expires_at !== null
      && new Date(latest.promotion_expires_at).getTime() <= Date.now());

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : "The evaluation action failed."); }
    finally { setBusy(null); }
  }

  async function createSuite() {
    if (!activeActivation) { setError("An active Sprint 11A staging authorization is required."); return; }
    await run("create", () => createAIEvaluationSuite(activeActivation.id),
      "A content-free, version-pinned evaluation suite was created.");
  }

  async function submitCase(event: FormEvent) {
    event.preventDefault();
    if (!latest || latest.status !== "collecting") return;
    await run("case", () => recordAIEvaluationCase(latest.id, draft),
      "Observed aggregate benchmark result recorded without prompt, document or model response content.");
    setDraft((current) => ({ ...initialCase,
      document_type: current.document_type === "chief_engineer_report" ? "engine_log" : "chief_engineer_report" }));
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Sprint 11B · measured promotion</p>
      <h1 className="mt-3 text-3xl font-semibold">AI quality, safety and cost evaluation</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">Promotion is fail-closed and pinned to the Sprint 11A model, prompt and schema bundle. This ledger stores only aggregate observations and hashes—never document text, prompts, expected answers, provider responses or keys.</p>
    </section>

    {(message || error) && <div role="status" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        ["Cases", latest ? `${latest.summary.case_count}/${latest.summary.required_case_count}` : "0/12"],
        ["Thresholds", latest?.summary.thresholds_passed ? "Passed" : "Not passed"],
        ["Independent reviews", latest?.summary.independent_reviews_complete ? "Complete" : "Incomplete"],
        ["Promotion active", latest?.summary.promotion_active ? "Yes" : "No"],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold text-slate-900">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Start a version-pinned evaluation attempt</h2>
      <p className="mt-2 text-sm text-slate-600">Active activation: {activeActivation ? `${activeActivation.model} · ${activeActivation.id}` : "none"}</p>
      <button disabled={!activeActivation || busy !== null} onClick={() => void createSuite()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Create evaluation suite</button>
    </section>}

    {latest && <SuiteSummary item={latest} busy={busy} run={run} />}

    {latest?.status === "collecting" && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">Record an observed benchmark result</h2><p className="mt-1 text-sm text-slate-600">Replace every sample value with the observed aggregate from the referenced controlled artifact.</p></div><Badge value="content free" /></div>
      <form onSubmit={submitCase} className="mt-5 space-y-4">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Case key"><input required value={draft.case_key} onChange={(event) => setDraft({ ...draft, case_key: event.target.value })} className={controlClass} placeholder="ce-baseline-001" /></Field>
          <Field label="Document type"><select value={draft.document_type} onChange={(event) => setDraft({ ...draft, document_type: event.target.value as CaseDraft["document_type"] })} className={controlClass}><option value="chief_engineer_report">Chief Engineer report</option><option value="engine_log">Engine log</option></select></Field>
          <Field label="Scenario"><select value={draft.scenario_type} onChange={(event) => setDraft({ ...draft, scenario_type: event.target.value as Scenario })} className={controlClass}><option value="baseline">Baseline</option><option value="prompt_injection">Prompt injection</option><option value="malformed_input">Malformed input</option><option value="cross_tenant">Cross tenant</option><option value="restricted_data">Restricted data</option></select></Field>
          <Field label="Result"><select value={draft.result} onChange={(event) => { const result = event.target.value as "pass" | "fail"; setDraft({ ...draft, result, boundary_control_passed: result === "pass" }); }} className={controlClass}><option value="pass">Pass</option><option value="fail">Fail</option></select></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["True positive", "field_true_positive"], ["False positive", "field_false_positive"],
            ["False negative", "field_false_negative"], ["Extracted claims", "extracted_claim_count"],
            ["Unsupported", "unsupported_claim_count"], ["Quotes checked", "source_quote_checked_count"],
            ["Quotes valid", "source_quote_valid_count"], ["Human approved", "human_approved_count"],
            ["Human edited", "human_edited_count"], ["Human rejected", "human_rejected_count"],
            ["Latency ms", "latency_ms"], ["Input tokens", "input_tokens"],
            ["Output tokens", "output_tokens"], ["Observed cost µUSD", "observed_provider_cost_microusd"],
          ].map(([label, key]) => <NumberField key={key} label={label} value={draft[key as keyof CaseDraft] as number} onChange={(value) => setDraft({ ...draft, [key]: value })} />)}
        </div>
        <div className="grid gap-3 md:grid-cols-2"><Field label="Bounded evidence reference"><input required value={draft.evidence_reference} onChange={(event) => setDraft({ ...draft, evidence_reference: event.target.value })} className={controlClass} /></Field><Field label="Human verification note"><input required value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} className={controlClass} /></Field></div>
        <button disabled={busy !== null} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Record immutable result</button>
      </form>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Immutable case ledger</h2>
      <div className="mt-4 space-y-2">{latest?.cases.length ? latest.cases.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium">{item.case_key} · {item.document_type.replaceAll("_", " ")}</p><p className="mt-1 text-xs text-slate-500">{item.scenario_type.replaceAll("_", " ")} · {item.latency_ms} ms · SHA-256 {item.result_hash.slice(0, 12)}…</p></div><Badge value={item.result} /></div>) : <p className="text-sm text-slate-500">No benchmark observations recorded.</p>}</div>
    </section>
  </div>;
}

function SuiteSummary({ item, busy, run }: { item: AIEvaluationSuite; busy: string | null; run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void> }) {
  const roles = ["quality", "risk"] as const;
  const reviewed = useMemo(() => new Set(item.reviews.map((review) => review.review_role)), [item.reviews]);
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Attempt {item.attempt_number} · {item.benchmark_profile}</p><h2 className="mt-1 text-xl font-semibold">{item.activation_model}</h2><p className="mt-1 text-xs text-slate-500">Prompt {item.prompt_bundle_version} · Schema {item.schema_bundle_version} · {item.max_input_chars} chars · {item.max_output_tokens} output tokens</p></div><Badge value={item.status} /></div>
    {item.metrics && <div className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">{[
      ["Precision", percent(metric(item, "precision_bps"))], ["Recall", percent(metric(item, "recall_bps"))],
      ["Unsupported", percent(metric(item, "unsupported_claim_rate_bps"))], ["Quote validity", percent(metric(item, "source_quote_validity_bps"))],
      ["Override", percent(metric(item, "human_override_rate_bps"))], ["P95 latency", `${metric(item, "p95_latency_ms") ?? "—"} ms`],
    ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}</div>}
    {item.failure_reasons.length > 0 && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">Failed controls: {item.failure_reasons.join(", ")}</div>}
    <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
      <button disabled={busy !== null || item.status !== "collecting"} onClick={() => void run("finalize", () => finalizeAIEvaluationSuite(item.id), "Evaluation finalized; threshold result is now immutable.")} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Finalize thresholds</button>
      {roles.map((role) => <button key={role} disabled={busy !== null || reviewed.has(role) || !["review_ready", "promotion_ready"].includes(item.status)} onClick={() => void run(`review-${role}`, () => reviewAIEvaluationSuite(item.id, role, "approve"), `${role} review recorded.`)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold capitalize disabled:opacity-40">{role} approve</button>)}
      <button disabled={busy !== null || item.status !== "promotion_ready"} onClick={() => void run("promote", () => decideAIEvaluationPromotion(item.id, "promote_staging"), "The evaluated synthetic/de-identified staging bundle was promoted.")} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Admin promote staging</button>
      <button disabled={busy !== null || item.status !== "promotion_ready"} onClick={() => void run("hold", () => decideAIEvaluationPromotion(item.id, "hold"), "Promotion held.")} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">Admin hold</button>
      <button disabled={busy !== null || item.status !== "staging_promoted"} onClick={() => void run("revoke", () => revokeAIEvaluationPromotion(item.id), "Evaluation promotion revoked.")} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">Revoke promotion</button>
    </div>
    <p className="mt-3 text-xs text-slate-500">The requester, Quality reviewer and Risk reviewer must be three different people. Switch accounts between reviews; only Admin can promote.</p>
    {item.evaluation_hash && <p className="mt-3 break-all font-mono text-[10px] text-slate-400">Evaluation SHA-256: {item.evaluation_hash}</p>}
  </section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-semibold text-slate-600">{label}</span>{children}</label>; }
function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) { return <Field label={label}><input type="number" min={0} required value={value} onChange={(event) => onChange(Number(event.target.value))} className={controlClass} /></Field>; }
