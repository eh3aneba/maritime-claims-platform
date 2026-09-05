"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim } from "@/lib/api";
import {
  approveInitialAssessment,
  generateInitialAssessment,
  getInitialAssessment,
  getInitialAssessmentHistory,
  getInitialAssessmentVersion,
  reviewAssessmentSection,
  type AssessmentHistoryItem,
  type SourceAwareInitialAssessment,
} from "@/lib/assessment-api";
import { assessmentT, type AssessmentKey } from "@/lib/i18n-assessment";
import { humanizeFieldLabel } from "@/lib/format";
import type { Claim } from "@/lib/types";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function numberValue(value: unknown): number {
  return typeof value === "number" ? value : Number(value ?? 0) || 0;
}

function textValue(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

const sourceKeys: Record<string, AssessmentKey> = {
  claim: "source_claim",
  claim_fact: "source_claim_fact",
  document: "source_document",
  document_extraction: "source_document_extraction",
  document_requirement: "source_document_requirement",
  chronology_event: "source_chronology_event",
  evidence_conflict: "source_evidence_conflict",
  claim_issue: "source_claim_issue",
  cost_item: "source_cost_item",
  financial_flag: "source_financial_flag",
  reserve_history: "source_reserve_history",
  claim_task: "source_claim_task",
};

const stateKeys: Record<string, AssessmentKey> = {
  current: "current",
  stale: "stale",
  legacy_unbound: "legacy_unbound",
  draft: "draft",
  under_review: "under_review",
  approved: "approved",
  attention_required: "attention_required",
  open_review: "open_review",
  reviewed: "reviewedState",
  no_topics: "no_topics",
  no_items: "no_items",
  recorded: "recorded",
  not_recorded: "not_recorded",
  open_recovery_paths: "open_recovery_paths",
  no_open_recovery_path_recorded: "no_open_recovery_path_recorded",
  no_recovery_path_recorded: "no_recovery_path_recorded",
};

export default function InitialAssessmentPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const t = (key: AssessmentKey, values?: Record<string, string | number>) => assessmentT(locale, key, values);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [assessment, setAssessment] = useState<SourceAwareInitialAssessment | null>(null);
  const [history, setHistory] = useState<AssessmentHistoryItem[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Record<string, string>>({});

  function formatWhen(value: string) {
    try {
      return new Intl.DateTimeFormat(locale === "fa" ? "fa-IR" : "en-GB", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value));
    } catch {
      return value;
    }
  }

  function stateLabel(value: unknown) {
    const raw = textValue(value);
    const key = stateKeys[raw];
    return key ? t(key) : humanizeFieldLabel(raw);
  }

  function sourceKindLabel(kind: string) {
    const key = sourceKeys[kind];
    return key ? t(key) : humanizeFieldLabel(kind);
  }

  async function loadWorkspace(preferredAssessmentId?: string | null) {
    try {
      const [claimResult, historyResult] = await Promise.all([
        getClaim(id),
        getInitialAssessmentHistory(id),
      ]);
      let assessmentResult: SourceAwareInitialAssessment | null = null;
      if (preferredAssessmentId) {
        try {
          assessmentResult = await getInitialAssessmentVersion(id, preferredAssessmentId);
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 404) throw e;
          assessmentResult = await getInitialAssessment(id);
        }
      } else {
        assessmentResult = await getInitialAssessment(id);
      }
      setClaim(claimResult);
      setHistory(historyResult.items);
      setAssessment(assessmentResult);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : t("loadError"));
    }
  }

  useEffect(() => {
    void loadWorkspace(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function generate(allow: boolean) {
    setBusy(true);
    setError("");
    try {
      const generated = await generateInitialAssessment(id, {
        allow_if_not_ready: allow,
        override_reason: allow
          ? "Preliminary assessment required while outstanding evidence is being obtained."
          : null,
      });
      setEditing({});
      await loadWorkspace(generated.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setError(t("generationConflict"));
      else if (e instanceof ApiError && e.status === 403) setError(t("permissionError"));
      else if (e instanceof ApiError && e.status === 422) setError(t("validationError"));
      else setError(e instanceof ApiError ? e.detail : t("generationError"));
    } finally {
      setBusy(false);
    }
  }

  async function review(sectionId: string, action: "approve" | "edit") {
    if (!assessment) return;
    if (!assessment.is_latest || !assessment.source_fingerprint || assessment.source_state !== "current") {
      setError(t("staleWrite"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await reviewAssessmentSection(id, sectionId, {
        action,
        text: action === "edit" ? editing[sectionId] : null,
        expected_source_fingerprint: assessment.source_fingerprint,
      });
      setEditing((current) => {
        const next = { ...current };
        delete next[sectionId];
        return next;
      });
      await loadWorkspace(assessment.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("staleWrite"));
        await loadWorkspace(assessment.id);
      } else if (e instanceof ApiError && e.status === 403) setError(t("permissionError"));
      else if (e instanceof ApiError && e.status === 422) setError(t("validationError"));
      else setError(e instanceof ApiError ? e.detail : t("reviewError"));
    } finally {
      setBusy(false);
    }
  }

  async function approveAll() {
    if (!assessment) return;
    if (!assessment.is_latest || !assessment.source_fingerprint || assessment.source_state !== "current") {
      setError(t("staleWrite"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const approved = await approveInitialAssessment(
        id,
        assessment.id,
        assessment.source_fingerprint,
        assessment.is_preliminary
          ? "Approved as preliminary assessment subject to outstanding evidence."
          : "Initial assessment reviewed.",
      );
      await loadWorkspace(approved.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("staleWrite"));
        await loadWorkspace(assessment.id);
      } else if (e instanceof ApiError && e.status === 403) setError(t("permissionError"));
      else if (e instanceof ApiError && e.status === 422) setError(t("validationError"));
      else setError(e instanceof ApiError ? e.detail : t("approvalError"));
    } finally {
      setBusy(false);
    }
  }

  if (!claim) return <div className="py-20 text-center text-sm text-slate-500">{t("loading")}</div>;

  const sourceWriteBlocked = Boolean(
    assessment && (!assessment.is_latest || assessment.source_state !== "current"),
  );
  const domains = assessment?.current_domain_status;
  const technical = asRecord(domains?.technical);
  const financial = asRecord(domains?.financial);
  const reserve = asRecord(domains?.reserve);
  const recovery = asRecord(domains?.recovery);
  const recoverySummary = asRecord(recovery.summary);
  const recoveryBlockers = Array.isArray(recovery.blockers) ? recovery.blockers : [];

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← {t("back")}</Link>
    <div className="mt-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
      <div>
        <p className="eyebrow" dir="ltr">{claim.claim_reference}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{t("title")}</h1>
        <p className="mt-2 text-sm text-slate-500">{t("subtitle")}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {assessment ? (
          <button disabled={busy} onClick={() => generate(true)} className="secondary-button">{t("generateNew")}</button>
        ) : (
          <button disabled={busy} onClick={() => generate(false)} className="secondary-button">{t("generateDraft")}</button>
        )}
        {assessment && assessment.status !== "approved" ? (
          <button disabled={busy || sourceWriteBlocked} onClick={approveAll} className="primary-button">
            {assessment.is_preliminary ? t("approvePreliminary") : t("approveFinal")}
          </button>
        ) : null}
        {assessment?.status === "approved" ? (
          <span className={`rounded-lg px-4 py-2 text-sm font-semibold ${assessment.is_preliminary ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`}>
            {assessment.is_preliminary ? t("approvedPreliminary") : t("approvedFinal")}
          </span>
        ) : null}
      </div>
    </div>

    {error ? <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" dir="auto">{error}</div> : null}

    {assessment && !assessment.is_latest ? (
      <section className="mt-5 rounded-xl border border-slate-300 bg-slate-50 p-5">
        <h2 className="text-sm font-semibold text-slate-950">{t("historicalTitle")}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          {t("historicalBody", { version: `v${assessment.version}`, latest: `v${assessment.latest_version}` })}
        </p>
      </section>
    ) : null}
    {assessment?.source_state === "stale" ? (
      <section className="mt-5 rounded-xl border border-rose-200 bg-rose-50 p-5">
        <h2 className="text-sm font-semibold text-rose-950">{t("staleTitle")}</h2>
        <p className="mt-2 text-sm leading-6 text-rose-800">{t("staleBody", { version: `v${assessment.version}` })}</p>
        <button disabled={busy} onClick={() => generate(true)} className="secondary-button mt-3">{t("generateNew")}</button>
      </section>
    ) : null}
    {assessment?.source_state === "legacy_unbound" ? (
      <section className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h2 className="text-sm font-semibold text-amber-950">{t("legacyTitle")}</h2>
        <p className="mt-2 text-sm leading-6 text-amber-800">{t("legacyBody")}</p>
        <button disabled={busy} onClick={() => generate(true)} className="secondary-button mt-3">{t("generateNew")}</button>
      </section>
    ) : null}

    <section className="panel mt-6 p-6">
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
        <div>
          <h2 className="section-title">{t("historyTitle")}</h2>
          <p className="section-subtitle">{t("historySubtitle")}</p>
        </div>
        <span className="rounded-lg bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-600" dir="ltr">{history.length}</span>
      </div>
      {history.length ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {history.map((item) => {
            const selected = assessment?.id === item.id;
            return <button key={item.id} type="button" disabled={busy} onClick={() => void loadWorkspace(item.id)} className={`rounded-xl border p-4 text-start transition ${selected ? "border-slate-900 bg-slate-50" : "border-slate-200 hover:border-slate-400"}`}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-slate-950" dir="ltr">v{item.version}</span>
                <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${item.is_latest ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>{item.is_latest ? t("latest") : t("historical")}</span>
              </div>
              <p className="mt-2 text-xs font-semibold text-slate-600">{stateLabel(item.status)} · {stateLabel(item.source_state)}</p>
              <p className="mt-1 text-xs text-slate-400" dir="ltr">{formatWhen(item.created_at)}</p>
              <p className="mt-3 text-xs font-semibold text-slate-700">{t("openVersion", { version: `v${item.version}` })}</p>
            </button>;
          })}
        </div>
      ) : <p className="mt-4 text-sm text-slate-500">{t("noHistory")}</p>}
    </section>

    {!assessment ? (
      <section className="panel mt-6 p-6">
        <h2 className="section-title">{t("emptyTitle")}</h2>
        <p className="section-subtitle">{t("emptySubtitle")}</p>
        <p className="mt-4 text-sm text-slate-600">{t("emptyBody")}</p>
        <button disabled={busy} onClick={() => generate(true)} className="secondary-button mt-4">{t("generatePreliminary")}</button>
      </section>
    ) : <>
      <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <div className="panel p-5"><p className="metric-label">{t("version")}</p><p className="metric-value" dir="ltr">v{assessment.version}</p></div>
        <div className="panel p-5"><p className="metric-label">{t("readiness")}</p><p className="metric-value" dir="ltr">{assessment.readiness_score}%</p><p className="mt-1 text-xs text-slate-500">{humanizeFieldLabel(assessment.readiness_state)}</p></div>
        <div className="panel p-5"><p className="metric-label">{t("status")}</p><p className="metric-value text-xl">{stateLabel(assessment.status)}</p>{assessment.approved_at ? <p className="mt-1 text-xs text-slate-500">{t("approvedAt", { date: formatWhen(assessment.approved_at) })}</p> : null}</div>
        <div className="panel p-5"><p className="metric-label">{t("classification")}</p><p className={`metric-value text-xl ${assessment.is_preliminary ? "text-amber-700" : "text-emerald-700"}`}>{assessment.is_preliminary ? t("preliminary") : t("ready")}</p></div>
        <div className="panel p-5"><p className="metric-label">{t("sourceState")}</p><p className={`metric-value text-xl ${assessment.source_state === "current" ? "text-emerald-700" : "text-rose-700"}`}>{stateLabel(assessment.source_state)}</p>{assessment.source_fingerprint ? <p className="mt-1 truncate font-mono text-[10px] text-slate-400" title={assessment.source_fingerprint} dir="ltr">{assessment.source_fingerprint}</p> : null}</div>
      </section>

      <section className="panel mt-5 p-6">
        <h2 className="section-title">{t("currentContextTitle")}</h2>
        <p className="section-subtitle">{t("currentContextBody")}</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-semibold text-slate-950">{t("technical")}</p><p className="mt-1 text-sm text-slate-600">{stateLabel(technical.state)}</p><p className="mt-3 text-xs text-slate-500">{t("topics", { count: numberValue(technical.topic_count) })}</p><p className="text-xs text-slate-500">{t("unreviewed", { count: numberValue(technical.unreviewed_topic_count) })}</p><p className="text-xs text-slate-500">{t("staleDecisions", { count: numberValue(technical.stale_human_decision_count) })}</p></div>
          <div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-semibold text-slate-950">{t("financial")}</p><p className="mt-1 text-sm text-slate-600">{stateLabel(financial.state)}</p><p className="mt-3 text-xs text-slate-500">{t("costItems", { count: numberValue(financial.cost_item_count) })}</p><p className="text-xs text-slate-500">{t("openReview", { count: numberValue(financial.open_cost_review_count) })}</p><p className="text-xs text-slate-500">{t("openFlags", { count: numberValue(financial.open_financial_flag_count) })}</p></div>
          <div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-semibold text-slate-950">{t("reserve")}</p><p className="mt-1 text-sm text-slate-600">{stateLabel(reserve.state)}</p><p className="mt-3 text-xs text-slate-500" dir="auto">{reserve.state === "recorded" ? t("reserveRecorded", { currency: textValue(reserve.currency), amount: textValue(reserve.amount) }) : t("reserveNotRecorded")}</p></div>
          <div className="rounded-xl border border-slate-200 p-4"><p className="text-sm font-semibold text-slate-950">{t("recovery")}</p><p className="mt-1 text-sm text-slate-600">{stateLabel(recovery.state)}</p><p className="mt-3 text-xs text-slate-500">{t("recoveryBlockers", { count: recoveryBlockers.length })}</p><p className="text-xs text-slate-500">{t("recoveryDecisions", { count: numberValue(recoverySummary.human_decision_count) })}</p><p className="text-xs text-slate-500">{t("recoveryActions", { count: numberValue(recoverySummary.human_action_count) })}</p></div>
        </div>
        <p className="mt-4 text-xs font-medium text-slate-500">{t("contextNotice")}</p>
      </section>

      {assessment.blocking_items.length ? (
        <section className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-5"><h2 className="text-sm font-semibold text-amber-950">{t("blockingTitle")}</h2><ul className="mt-3 list-disc space-y-1 ps-5 text-sm text-amber-900" dir="auto">{assessment.blocking_items.map((item) => <li key={item}>{item}</li>)}</ul><p className="mt-3 text-xs text-amber-700">{t("blockingBody")}</p></section>
      ) : null}

      {assessment.status === "approved" ? (
        <section className={`mt-5 rounded-xl border p-5 ${assessment.is_preliminary ? "border-amber-300 bg-amber-50" : "border-emerald-300 bg-emerald-50"}`}><h2 className={`text-sm font-semibold ${assessment.is_preliminary ? "text-amber-950" : "text-emerald-950"}`}>{assessment.is_preliminary ? t("approvedPreliminaryTitle") : t("approvedFinalTitle")}</h2><p className={`mt-2 text-xs leading-5 ${assessment.is_preliminary ? "text-amber-800" : "text-emerald-800"}`}>{assessment.is_preliminary ? t("approvedPreliminaryBody") : t("approvedFinalBody")}</p>{assessment.approved_content_hash ? <p className="mt-3 break-all font-mono text-[10px] text-slate-500" dir="ltr">{t("approvedDigest")}: {assessment.approved_content_hash}</p> : null}</section>
      ) : null}

      <div className="mt-6 space-y-5">{assessment.sections.map((section) => {
        const text = section.approved_text ?? section.draft_text;
        const reviewed = section.status !== "pending";
        const canWrite = assessment.is_latest && assessment.status !== "approved" && assessment.source_state === "current";
        return <section key={section.id} className="panel p-6">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><p className="eyebrow" dir="ltr">{String(section.sort_order / 10).padStart(2, "0")}</p><h2 className="section-title mt-1" dir="auto">{section.title}</h2><div className="mt-1 flex flex-wrap items-center gap-2"><span className={`text-xs font-semibold uppercase tracking-wide ${reviewed ? "text-emerald-700" : "text-slate-400"}`}>{reviewed ? t("reviewed", { status: stateLabel(section.status) }) : t("pending")}</span>{section.reviewed_at ? <span className="text-xs text-slate-400" dir="ltr">{formatWhen(section.reviewed_at)}</span> : null}</div></div><div className="flex gap-2">{canWrite && !reviewed ? <button disabled={busy} onClick={() => review(section.id, "approve")} className="secondary-button">{t("approve")}</button> : null}{canWrite ? <button disabled={busy} onClick={() => setEditing({ ...editing, [section.id]: editing[section.id] ?? text })} className="secondary-button">{t("edit")}</button> : <span className="rounded-lg bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-600">{t("locked")}</span>}</div></div>
          {editing[section.id] !== undefined && canWrite ? <div className="mt-4"><textarea rows={7} dir="auto" className="field resize-y" value={editing[section.id]} onChange={(event) => setEditing({ ...editing, [section.id]: event.target.value })} /><div className="mt-2 flex gap-2"><button disabled={busy} onClick={() => review(section.id, "edit")} className="primary-button">{t("saveEdit")}</button><button onClick={() => { const next = { ...editing }; delete next[section.id]; setEditing(next); }} className="secondary-button">{t("cancel")}</button></div></div> : <div className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-700" dir="auto">{text}</div>}
          <details className="mt-5 border-t border-slate-200 pt-4"><summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">{t("sources", { count: section.source_manifest.length })}</summary><div className="mt-3 space-y-2">{section.source_manifest.length ? section.source_manifest.map((source, index) => <div key={`${source.id}-${index}`} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600" dir="auto"><span className="font-semibold">{sourceKindLabel(source.kind)}</span><span className="text-slate-400"> · </span>{source.label}</div>) : <p className="text-xs text-slate-400">{t("noSources")}</p>}</div></details>
        </section>;
      })}</div>

      {assessment.status !== "approved" ? <div className="mt-6 flex justify-end"><button disabled={busy || sourceWriteBlocked} onClick={approveAll} className="primary-button">{assessment.is_preliminary ? t("approvePreliminary") : t("approveFinal")}</button></div> : null}
    </>}
  </div>;
}
