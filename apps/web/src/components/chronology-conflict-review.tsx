"use client";

import { useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  type MatureClaimChronologyResponse,
  type MatureEvidenceConflict,
  resolveEvidenceConflictStateAware,
} from "@/lib/chronology-maturity-api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import {
  chronologyT,
  conflictStatusLabel,
  conflictTypeLabel,
  materialityLabel,
  type ChronologyKey,
} from "@/lib/i18n-chronology";
import type { Locale } from "@/lib/i18n";
import type { EvidenceConflictStatus } from "@/lib/types";

const materialityClasses: Record<string, string> = {
  low: "bg-slate-100 text-slate-600",
  medium: "bg-amber-50 text-amber-800",
  high: "bg-orange-50 text-orange-800",
  critical: "bg-red-50 text-red-800",
};

const stateClasses: Record<string, string> = {
  none: "bg-slate-100 text-slate-600",
  current: "bg-emerald-50 text-emerald-700",
  stale: "bg-amber-50 text-amber-800",
};

type ChronologyEvent = MatureClaimChronologyResponse["events"][number];
type ReviewStatus = Exclude<EvidenceConflictStatus, "open">;

function formatConflictValue(value: unknown) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (record.date || record.time) {
      return [record.date, record.time, record.timezone].filter(Boolean).join(" ");
    }
  }
  return formatStructuredValue(value);
}

function sourceForSide(events: ChronologyEvent[], eventId: string | null, extractionId: string | null) {
  const event = eventId ? events.find((candidate) => candidate.id === eventId) : undefined;
  if (!event) return null;
  const evidence = extractionId
    ? event.evidence.find((candidate) => candidate.extraction_id === extractionId)
    : event.evidence[0];
  return { event, evidence: evidence ?? null };
}

function shortHash(value: string | null) {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

export function ChronologyConflictReview({
  claimId,
  conflict,
  events,
  locale,
  onReload,
}: {
  claimId: string;
  conflict: MatureEvidenceConflict;
  events: ChronologyEvent[];
  locale: Locale;
  onReload: () => Promise<void>;
}) {
  const ct = (key: ChronologyKey, values?: Record<string, string | number>) => chronologyT(locale, key, values);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [reReview, setReReview] = useState(false);
  const [localStale, setLocalStale] = useState(false);
  const [localError, setLocalError] = useState("");

  const stateAvailable = Boolean(conflict.state_fingerprint && conflict.state_version >= 1);
  const sourceA = useMemo(
    () => sourceForSide(events, conflict.event_a_id, conflict.evidence_a_extraction_id),
    [events, conflict.event_a_id, conflict.evidence_a_extraction_id],
  );
  const sourceB = useMemo(
    () => sourceForSide(events, conflict.event_b_id, conflict.evidence_b_extraction_id),
    [events, conflict.event_b_id, conflict.evidence_b_extraction_id],
  );
  const canReview = conflict.status === "open" || reReview;
  const severity = materialityLabel(locale, conflict.materiality);

  async function submit(status: ReviewStatus) {
    const trimmed = note.trim();
    if (trimmed.length < 3) {
      setLocalError(ct("noteRequired"));
      return;
    }
    if (!conflict.state_fingerprint || conflict.state_version < 1) {
      setLocalError(ct("stateUnavailable"));
      return;
    }

    setBusy(true);
    setLocalError("");
    try {
      await resolveEvidenceConflictStateAware(claimId, conflict.id, {
        status,
        note: trimmed,
        expected_state_fingerprint: conflict.state_fingerprint,
        expected_state_version: conflict.state_version,
        confirm_re_review: reReview,
      });
      setNote("");
      setReReview(false);
      setLocalStale(false);
      await onReload();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setLocalStale(true);
        setLocalError(ct("staleConflictError"));
      } else {
        setLocalError(error instanceof ApiError ? error.detail : ct("conflictUpdateError"));
      }
    } finally {
      setBusy(false);
    }
  }

  async function refreshCurrentState() {
    setBusy(true);
    setLocalError("");
    try {
      await onReload();
      setLocalStale(false);
    } catch (error) {
      setLocalError(error instanceof ApiError ? error.detail : ct("loadError"));
    } finally {
      setBusy(false);
    }
  }

  function renderSource(label: "A" | "B", source: ReturnType<typeof sourceForSide>) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{ct("sourceSide", { side: label })}</p>
        {source ? (
          <div className="mt-2 space-y-1 text-xs text-slate-600">
            <p className="font-semibold text-slate-800" dir="auto">{source.event.title}</p>
            {source.evidence ? (
              <>
                <p dir="ltr">{source.evidence.document_name} · {humanizeFieldLabel(source.evidence.field_path)}</p>
                {source.evidence.source_locator_value ? (
                  <p><span className="font-semibold">{ct("sourceLocator")}:</span>{" "}<span dir="ltr">{source.evidence.source_locator_value}</span></p>
                ) : null}
                {source.evidence.source_quote ? (
                  <p className="border-l-2 border-slate-300 pl-2 leading-5" dir="auto">{source.evidence.source_quote}</p>
                ) : null}
              </>
            ) : <p>{ct("sourceUnavailable")}</p>}
          </div>
        ) : <p className="mt-2 text-xs text-slate-500">{ct("sourceUnavailable")}</p>}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 p-4" data-testid={`chronology-conflict-${conflict.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950" dir="auto">{conflict.topic}</p>
          <p className="mt-1 text-xs uppercase tracking-wide text-slate-400">
            {conflictTypeLabel(locale, conflict.conflict_type)} · {conflictStatusLabel(locale, conflict.status)}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${stateClasses[conflict.decision_state] ?? stateClasses.none}`}>
              {ct(`state.${conflict.decision_state}` as ChronologyKey)}
            </span>
            <span className="text-[11px] text-slate-400" dir="ltr">v{conflict.state_version} · {shortHash(conflict.state_fingerprint)}</span>
          </div>
        </div>
        <span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${materialityClasses[conflict.materiality]}`}>
          {ct("conflictSeverity", { value: severity })}
        </span>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-600" dir="auto">{conflict.description}</p>
      <div className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
        <div><span className="font-semibold">A:</span>{" "}<span dir="ltr">{formatConflictValue(conflict.value_a)}</span></div>
        <div><span className="font-semibold">B:</span>{" "}<span dir="ltr">{formatConflictValue(conflict.value_b)}</span></div>
        {conflict.difference_minutes ? <div><span className="font-semibold">{ct("difference")}:</span>{" "}<span dir="ltr">{conflict.difference_minutes}</span> {ct("minutes")}</div> : null}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {renderSource("A", sourceA)}
        {renderSource("B", sourceB)}
      </div>

      {conflict.resolution_note ? (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
          <span className="font-semibold">{ct("currentDisposition")}:</span>{" "}
          <span>{conflictStatusLabel(locale, conflict.status)}</span>
          <span className="mx-1">·</span>
          <span dir="auto">{conflict.resolution_note}</span>
        </div>
      ) : null}

      {conflict.decision_history.length ? (
        <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">
            {ct("decisionHistory", { count: conflict.decision_history.length })}
          </summary>
          <div className="mt-3 space-y-3">
            {[...conflict.decision_history].reverse().map((decision) => (
              <div key={decision.id} className="border-t border-slate-200 pt-3 first:border-0 first:pt-0 text-xs text-slate-600">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-800">#{decision.decision_number}</span>
                  <span>{conflictStatusLabel(locale, decision.status)}</span>
                  <span dir="ltr">v{decision.state_version}</span>
                  <span dir="ltr">{new Date(decision.decided_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-GB")}</span>
                </div>
                <p className="mt-1" dir="auto">{decision.note}</p>
                <p className="mt-1 text-[11px] text-slate-400" dir="ltr">{shortHash(decision.decision_hash)}</p>
              </div>
            ))}
          </div>
        </details>
      ) : (
        <p className="mt-3 text-xs text-slate-400">{ct("noDecisionHistory")}</p>
      )}

      {!stateAvailable ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">{ct("stateUnavailable")}</div>
      ) : null}

      {localError ? (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700" role="alert" dir="auto">{localError}</div>
      ) : null}

      {localStale ? (
        <button className="secondary-button mt-3" disabled={busy} onClick={refreshCurrentState}>
          {ct("refreshCurrentState")}
        </button>
      ) : null}

      {conflict.status !== "open" && !reReview ? (
        <button
          className="secondary-button mt-3"
          disabled={busy || !stateAvailable || localStale}
          onClick={() => { setReReview(true); setLocalError(""); }}
        >
          {ct("deliberateReReview")}
        </button>
      ) : null}

      {reReview ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
          {ct("reReviewWarning")}
        </div>
      ) : null}

      {canReview ? (
        <>
          <textarea
            className="field mt-3 min-h-20"
            placeholder={ct("notePlaceholder")}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            dir="auto"
            disabled={busy || localStale}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <button disabled={busy || !stateAvailable || localStale} className="secondary-button" onClick={() => submit("explained")}>{ct("action.explain")}</button>
            <button disabled={busy || !stateAvailable || localStale} className="secondary-button" onClick={() => submit("accepted_difference")}>{ct("action.acceptDifference")}</button>
            <button disabled={busy || !stateAvailable || localStale} className="secondary-button" onClick={() => submit("resolved")}>{ct("action.resolve")}</button>
            <button disabled={busy || !stateAvailable || localStale} className="secondary-button" onClick={() => submit("irrelevant")}>{ct("action.irrelevant")}</button>
            {reReview ? (
              <button className="secondary-button" disabled={busy} onClick={() => { setReReview(false); setLocalError(""); }}>
                {ct("cancelReReview")}
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
