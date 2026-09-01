"use client";

import { useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  decideMarineRuleEvaluation,
  type MarineRuleDecision,
  type MarineRuleDecisionAction,
} from "@/lib/marine-rules-api";

export interface MarineRuleEvaluationView {
  rule_id: string;
  rule_version: string;
  definition_hash: string;
  family: string;
  topic: string;
  source_title: string;
  source_reference: string;
  status: "triggered" | "not_triggered" | "insufficient_evidence" | "not_applicable";
  evidence_used: Array<Record<string, unknown>>;
  missing_prerequisites: string[];
  rationale: string;
  candidate_implication: string;
  recommended_action: string;
  evaluation_hash: string;
  latest_decision?: MarineRuleDecision | null;
}

export interface MarineRuleSummaryView {
  marine_registry_version?: string | null;
  marine_registry_hash?: string | null;
  marine_rule_evaluations?: MarineRuleEvaluationView[];
  marine_rule_counts?: Record<string, number>;
  marine_evaluated_at?: string | null;
  marine_rule_run_id?: string | null;
  human_authority_boundary?: string | null;
}

function statusTone(status: MarineRuleEvaluationView["status"]) {
  if (status === "triggered") return "border-orange-200 bg-orange-50 text-orange-800";
  if (status === "insufficient_evidence") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "not_triggered") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function actionLabel(action: MarineRuleDecisionAction) {
  if (action === "not_applicable") return "Not applicable";
  return action.charAt(0).toUpperCase() + action.slice(1);
}

function evidenceLabel(row: Record<string, unknown>) {
  const kind = typeof row.kind === "string" ? row.kind.replaceAll("_", " ") : "evidence";
  const field = typeof row.field_path === "string" ? row.field_path : typeof row.field === "string" ? row.field : null;
  const description = typeof row.description === "string" ? row.description : null;
  const value = row.value ?? row.amount ?? null;
  const suffix = value === null || value === undefined ? "" : ` · ${typeof value === "object" ? JSON.stringify(value) : String(value)}`;
  return `${kind}${field ? ` · ${field}` : ""}${description ? ` · ${description}` : ""}${suffix}`;
}

function MarineRuleCard({
  claimId,
  runId,
  row,
  onRefresh,
}: {
  claimId: string;
  runId: string | null;
  row: MarineRuleEvaluationView;
  onRefresh: () => Promise<void>;
}) {
  const [action, setAction] = useState<MarineRuleDecisionAction>("accept");
  const [note, setNote] = useState("");
  const [editedImplication, setEditedImplication] = useState("");
  const [editedAction, setEditedAction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);

  async function submitDecision() {
    setError("");
    if (!runId) { setError("Refresh rules before recording a disposition."); return; }
    if (note.trim().length < 5) { setError("Add a short review note before saving."); return; }
    if (action === "edit" && !editedImplication.trim() && !editedAction.trim()) {
      setError("Edit requires replacement implication or recommended-action wording.");
      return;
    }
    setSubmitting(true);
    try {
      await decideMarineRuleEvaluation(claimId, runId, row.rule_id, {
        evaluation_hash: row.evaluation_hash,
        action,
        note: note.trim(),
        edited_candidate_implication: action === "edit" && editedImplication.trim() ? editedImplication.trim() : null,
        edited_recommended_action: action === "edit" && editedAction.trim() ? editedAction.trim() : null,
      });
      setNote("");
      setEditedImplication("");
      setEditedAction("");
      setReviewOpen(false);
      await onRefresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Human disposition could not be saved.");
    } finally {
      setSubmitting(false);
    }
  }

  return <article className="rounded-xl border border-slate-200 bg-white p-4">
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-2 py-1 text-[11px] font-bold uppercase tracking-wide ${statusTone(row.status)}`}>{row.status.replaceAll("_", " ")}</span>
          <span className="text-[11px] font-semibold text-slate-400">{row.rule_id} · v{row.rule_version}</span>
        </div>
        <h3 className="mt-2 text-sm font-semibold text-slate-950">{row.source_reference} · {row.topic.replaceAll("_", " ")}</h3>
        <p className="mt-1 text-xs text-slate-500">{row.source_title} · {row.family.replaceAll("_", " ")}</p>
      </div>
      <div className="text-right text-[10px] text-slate-400" title={row.evaluation_hash}>Evaluation {row.evaluation_hash.slice(0, 10)}…</div>
    </div>

    <div className="mt-4 grid gap-3 lg:grid-cols-3">
      <div className="rounded-lg bg-slate-50 p-3"><p className="text-[10px] font-bold uppercase tracking-[.12em] text-slate-500">Rationale</p><p className="mt-1 text-xs leading-5 text-slate-700">{row.rationale}</p></div>
      <div className="rounded-lg bg-cyan-50 p-3"><p className="text-[10px] font-bold uppercase tracking-[.12em] text-cyan-700">Candidate implication</p><p className="mt-1 text-xs leading-5 text-slate-700">{row.candidate_implication}</p></div>
      <div className="rounded-lg bg-violet-50 p-3"><p className="text-[10px] font-bold uppercase tracking-[.12em] text-violet-700">Recommended human action</p><p className="mt-1 text-xs leading-5 text-slate-700">{row.recommended_action}</p></div>
    </div>

    {(row.evidence_used.length || row.missing_prerequisites.length) ? <div className="mt-3 grid gap-3 lg:grid-cols-2">
      <div className="rounded-lg border border-slate-200 p-3"><p className="text-[10px] font-bold uppercase tracking-[.12em] text-slate-500">Evidence used</p>{row.evidence_used.length ? <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-600">{row.evidence_used.map((item, index) => <li key={`${row.rule_id}-e-${index}`}>• {evidenceLabel(item)}</li>)}</ul> : <p className="mt-2 text-xs text-slate-400">No qualifying controlled evidence used.</p>}</div>
      <div className="rounded-lg border border-slate-200 p-3"><p className="text-[10px] font-bold uppercase tracking-[.12em] text-slate-500">Missing prerequisites</p>{row.missing_prerequisites.length ? <ul className="mt-2 space-y-1 text-xs leading-5 text-amber-800">{row.missing_prerequisites.map((item) => <li key={item}>• {item}</li>)}</ul> : <p className="mt-2 text-xs text-emerald-700">No missing prerequisites identified by this rule.</p>}</div>
    </div> : null}

    {row.latest_decision ? <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-[10px] font-bold uppercase tracking-[.12em] text-emerald-800">Latest human disposition · {actionLabel(row.latest_decision.action)}</p><p className="text-[10px] text-emerald-700">Decision #{row.latest_decision.decision_number} · {row.latest_decision.decision_hash.slice(0, 10)}…</p></div>
      <p className="mt-1 text-xs leading-5 text-emerald-900">{row.latest_decision.note}</p>
      {row.latest_decision.edited_candidate_implication ? <p className="mt-2 text-xs text-slate-700"><strong>Human-edited implication:</strong> {row.latest_decision.edited_candidate_implication}</p> : null}
      {row.latest_decision.edited_recommended_action ? <p className="mt-2 text-xs text-slate-700"><strong>Human-edited action:</strong> {row.latest_decision.edited_recommended_action}</p> : null}
    </div> : null}

    <div className="mt-3 flex justify-end"><button className="secondary-button px-3 py-2 text-xs" onClick={() => setReviewOpen((value) => !value)}>{reviewOpen ? "Close review" : row.latest_decision ? "Add disposition" : "Review rule"}</button></div>
    {reviewOpen ? <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
        <label><span className="label">Disposition</span><select className="field" value={action} onChange={(e) => setAction(e.target.value as MarineRuleDecisionAction)}><option value="accept">Accept as review prompt</option><option value="edit">Edit wording</option><option value="dismiss">Dismiss</option><option value="not_applicable">Mark not applicable</option></select></label>
        <label><span className="label">Review note</span><input className="field" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Record the human reasoning and evidence reviewed" /></label>
      </div>
      {action === "edit" ? <div className="mt-3 grid gap-3 lg:grid-cols-2"><label><span className="label">Edited candidate implication</span><textarea className="field min-h-24" value={editedImplication} onChange={(e) => setEditedImplication(e.target.value)} placeholder={row.candidate_implication} /></label><label><span className="label">Edited recommended action</span><textarea className="field min-h-24" value={editedAction} onChange={(e) => setEditedAction(e.target.value)} placeholder={row.recommended_action} /></label></div> : null}
      {error ? <p className="mt-3 text-xs font-semibold text-red-700">{error}</p> : null}
      <div className="mt-3 flex justify-end"><button disabled={submitting} className="primary-button px-3 py-2 text-xs" onClick={submitDecision}>{submitting ? "Saving…" : "Record disposition"}</button></div>
      <p className="mt-2 text-[11px] leading-4 text-slate-500">The disposition is append-only and linked to this exact evaluation hash. It does not rewrite the rule definition, evaluation, claim fact, coverage position, reserve or settlement.</p>
    </div> : null}
  </article>;
}

export function MarineRulesPanel({
  claimId,
  summary,
  onRefresh,
}: {
  claimId: string;
  summary: MarineRuleSummaryView;
  onRefresh: () => Promise<void>;
}) {
  const evaluations = summary.marine_rule_evaluations ?? [];
  const attention = useMemo(() => evaluations.filter((row) => row.status === "triggered" || row.status === "insufficient_evidence"), [evaluations]);
  const other = useMemo(() => evaluations.filter((row) => row.status !== "triggered" && row.status !== "insufficient_evidence"), [evaluations]);
  const counts = summary.marine_rule_counts ?? {};

  return <section className="panel mt-6 p-6">
    <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
      <div><p className="eyebrow">Phase 12B · Explainable Marine Rules Engine</p><h2 className="mt-2 section-title">Marine rule evaluations</h2><p className="section-subtitle">Versioned deterministic issue-spotting with evidence lineage, missing prerequisites and separate human dispositions.</p></div>
      {summary.marine_registry_version ? <div className="rounded-lg bg-slate-50 px-3 py-2 text-right text-[11px] text-slate-500"><div>Registry {summary.marine_registry_version}</div>{summary.marine_registry_hash ? <div title={summary.marine_registry_hash}>Hash {summary.marine_registry_hash.slice(0, 12)}…</div> : null}</div> : null}
    </div>

    {summary.human_authority_boundary ? <div className="mt-4 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-xs leading-5 text-cyan-900">{summary.human_authority_boundary}</div> : null}

    <div className="mt-4 flex flex-wrap gap-2">
      {(["triggered", "insufficient_evidence", "not_triggered", "not_applicable"] as const).map((status) => <span key={status} className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${statusTone(status)}`}>{status.replaceAll("_", " ")}: {counts[status] ?? 0}</span>)}
    </div>

    {!evaluations.length ? <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-7 text-center text-sm text-slate-500">Refresh rules to generate the current evidence-linked marine evaluations.</div> : <>
      <div className="mt-6"><div className="flex items-center justify-between gap-3"><h3 className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">Attention required</h3><span className="text-xs text-slate-400">{attention.length}</span></div><div className="mt-3 space-y-3">{attention.length ? attention.map((row) => <MarineRuleCard key={`${row.rule_id}-${row.evaluation_hash}`} claimId={claimId} runId={summary.marine_rule_run_id ?? null} row={row} onRefresh={onRefresh} />) : <div className="rounded-xl border border-dashed border-emerald-200 bg-emerald-50 p-5 text-center text-sm text-emerald-700">No triggered or evidence-insufficient marine rules.</div>}</div></div>
      {other.length ? <details className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-700">Show {other.length} not-triggered / not-applicable evaluations</summary><div className="mt-4 space-y-3">{other.map((row) => <MarineRuleCard key={`${row.rule_id}-${row.evaluation_hash}`} claimId={claimId} runId={summary.marine_rule_run_id ?? null} row={row} onRefresh={onRefresh} />)}</div></details> : null}
    </>}
  </section>;
}
