"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import type { Locale } from "@/lib/i18n";
import { reviewT, severityLabel, technicalStatusLabel } from "@/lib/i18n-review-support";
import {
  getTechnicalDecisionHistory,
  type MatureTechnicalMatrixRow,
  recordTechnicalDecision,
  type TechnicalDecisionAction,
  type TechnicalDecisionHistoryResponse,
  type TechnicalEvidenceItem,
} from "@/lib/technical-maturity-api";

const stateClasses: Record<string, string> = {
  none: "bg-slate-100 text-slate-600",
  current: "bg-emerald-50 text-emerald-700",
  stale: "bg-amber-50 text-amber-800",
};

function shortHash(value: string | null) {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function isTechnicalEvidenceItem(value: unknown): value is TechnicalEvidenceItem {
  return Boolean(
    value
      && typeof value === "object"
      && !Array.isArray(value)
      && "field_path" in value,
  );
}

function actionLabel(locale: Locale, action: TechnicalDecisionAction) {
  const labels: Record<TechnicalDecisionAction, [string, string]> = {
    keep_open: ["Keep investigation open", "تحقیق باز بماند"],
    supported_for_investigation: ["Supported for investigation", "برای ادامه تحقیق مؤید است"],
    not_supported: ["Not supported by current evidence", "با شواهد فعلی پشتیبانی نمی‌شود"],
    needs_more_evidence: ["Needs more evidence", "به شواهد بیشتری نیاز دارد"],
  };
  const [en, fa] = labels[action];
  return reviewT(locale, en, fa);
}

function stateLabel(locale: Locale, state: MatureTechnicalMatrixRow["decision_state"]) {
  if (state === "current") return reviewT(locale, "Current human disposition", "تصمیم انسانی فعلی");
  if (state === "stale") return reviewT(locale, "Prior disposition is stale", "تصمیم قبلی قدیمی شده است");
  return reviewT(locale, "No human disposition", "تصمیم انسانی ثبت نشده است");
}

function SourceEvidenceCard({
  claimId,
  item,
  locale,
}: {
  claimId: string;
  item: unknown;
  locale: Locale;
}) {
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  if (!isTechnicalEvidenceItem(item)) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-700" dir="auto">
        {formatStructuredValue(item)}
      </div>
    );
  }

  const sourceHref = item.document_id || item.extraction_id
    ? `/claims/${claimId}/evidence-matrix?document_id=${encodeURIComponent(item.document_id ?? "")}&extraction_id=${encodeURIComponent(item.extraction_id ?? "")}`
    : `/claims/${claimId}/evidence-matrix`;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400" dir="ltr">
            {humanizeFieldLabel(item.field_path)}
          </p>
          <p className="mt-1 text-sm font-semibold text-slate-800" dir="auto">
            {formatStructuredValue(item.value)}
          </p>
        </div>
        <Link className="text-xs font-semibold text-cyan-700 hover:text-cyan-900" href={sourceHref}>
          {r("Open source context", "باز کردن زمینه منبع")}
        </Link>
      </div>
      {item.source_locator_value ? (
        <p className="mt-2 text-xs text-slate-500">
          <span className="font-semibold">{r("Source locator", "نشانی منبع")}:</span>{" "}
          <span dir="ltr">{item.source_locator_value}</span>
          {item.source_locator_type ? <span dir="ltr"> ({item.source_locator_type})</span> : null}
        </p>
      ) : null}
      {item.source_quote ? (
        <blockquote className="mt-2 border-l-2 border-slate-300 pl-3 text-xs leading-5 text-slate-600" dir="auto">
          {item.source_quote}
        </blockquote>
      ) : null}
      {item.source_verified === true ? (
        <p className="mt-2 text-xs font-medium text-emerald-700">{r("Source verified", "منبع تأیید شده")}</p>
      ) : null}
    </div>
  );
}

function EvidenceList({
  claimId,
  items,
  empty,
  locale,
}: {
  claimId: string;
  items: unknown[];
  empty: string;
  locale: Locale;
}) {
  if (!items.length) return <p className="mt-2 text-sm text-slate-500">{empty}</p>;
  return (
    <div className="mt-3 space-y-2">
      {items.map((item, index) => (
        <SourceEvidenceCard claimId={claimId} item={item} key={index} locale={locale} />
      ))}
    </div>
  );
}

export function TechnicalInvestigationReview({
  claimId,
  row,
  locale,
  onReload,
}: {
  claimId: string;
  row: MatureTechnicalMatrixRow;
  locale: Locale;
  onReload: () => Promise<void>;
}) {
  const r = (en: string, fa: string) => reviewT(locale, en, fa);
  const [note, setNote] = useState("");
  const [history, setHistory] = useState<TechnicalDecisionHistoryResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reReview, setReReview] = useState(false);
  const [localStale, setLocalStale] = useState(false);
  const [localError, setLocalError] = useState("");

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistory(await getTechnicalDecisionHistory(claimId, row.key));
    } catch (error) {
      setHistoryError(
        error instanceof ApiError
          ? error.detail
          : r("Decision history could not be loaded.", "تاریخچه تصمیم قابل بارگذاری نیست."),
      );
    } finally {
      setHistoryLoading(false);
    }
  }, [claimId, row.key, locale]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const stateAvailable = Boolean(row.state_fingerprint && row.state_version >= 1);
  const hasPriorDecision = Boolean(row.latest_decision || history?.items.length);
  const canReview = !hasPriorDecision || reReview;

  async function submit(action: TechnicalDecisionAction) {
    const trimmed = note.trim();
    if (trimmed.length < 5) {
      setLocalError(r("Add a review note of at least 5 characters.", "یادداشت بازبینی حداقل ۵ نویسه وارد کنید."));
      return;
    }
    if (!row.state_fingerprint || row.state_version < 1) {
      setLocalError(r("Current evidence state is unavailable. Refresh before recording a decision.", "وضعیت فعلی شواهد در دسترس نیست. پیش از ثبت تصمیم صفحه را تازه کنید."));
      return;
    }

    setBusy(true);
    setLocalError("");
    try {
      await recordTechnicalDecision(claimId, row.key, {
        action,
        note: trimmed,
        expected_state_fingerprint: row.state_fingerprint,
        expected_state_version: row.state_version,
        confirm_re_review: reReview,
      });
      setNote("");
      setReReview(false);
      setLocalStale(false);
      await onReload();
      await loadHistory();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setLocalStale(true);
        setLocalError(r(
          "Technical evidence changed while you were reviewing it. Your draft is preserved. Refresh the current state before submitting again.",
          "شواهد فنی هنگام بازبینی تغییر کرده است. پیش‌نویس شما حفظ شد. پیش از ارسال دوباره، وضعیت فعلی را تازه کنید.",
        ));
      } else if (error instanceof ApiError && error.status === 403) {
        setLocalError(r(
          "You do not have permission to record this technical disposition.",
          "شما مجوز ثبت این تصمیم فنی را ندارید.",
        ));
      } else {
        setLocalError(
          error instanceof ApiError
            ? error.detail
            : r("Technical disposition could not be recorded.", "تصمیم فنی ثبت نشد."),
        );
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
      await loadHistory();
      setLocalStale(false);
    } catch (error) {
      setLocalError(
        error instanceof ApiError
          ? error.detail
          : r("Technical review could not be refreshed.", "بازبینی فنی تازه‌سازی نشد."),
      );
    } finally {
      setBusy(false);
    }
  }

  const latest = row.latest_decision;

  return (
    <article className="panel p-6" data-testid={`technical-topic-${row.key}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">
            {r("Investigation priority", "اولویت تحقیق")}: {severityLabel(locale, row.severity)} · {technicalStatusLabel(locale, row.status)}
          </p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950" dir="auto">{row.title}</h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${stateClasses[row.decision_state] ?? stateClasses.none}`}>
              {stateLabel(locale, row.decision_state)}
            </span>
            <span className="text-[11px] text-slate-400" dir="ltr">
              v{row.state_version} · {shortHash(row.state_fingerprint)}
            </span>
          </div>
        </div>
      </div>

      <p className="mt-3 text-sm leading-6 text-slate-600" dir="auto">{row.explanation}</p>

      {row.decision_state === "stale" ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900" role="status">
          {r(
            "Underlying reviewed evidence has changed since the prior human disposition. The old decision remains in history and must not be treated as current without deliberate re-review.",
            "شواهد بازبینی‌شده زیربنایی پس از تصمیم انسانی قبلی تغییر کرده است. تصمیم قبلی در تاریخچه باقی می‌ماند و بدون بازبینی آگاهانه نباید تصمیم فعلی تلقی شود.",
          )}
        </div>
      ) : null}

      {latest ? (
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
          <p className="font-semibold text-slate-900">{r("Latest human investigation disposition", "آخرین تصمیم انسانی در تحقیق")}</p>
          <p className="mt-1">{actionLabel(locale, latest.action)} · <span dir="ltr">v{latest.state_version}</span></p>
          <p className="mt-1" dir="auto">{latest.note}</p>
          <p className="mt-1 text-[11px] text-slate-400" dir="ltr">
            {new Date(latest.decided_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-GB")} · {shortHash(latest.decision_hash)}
          </p>
        </div>
      ) : null}

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl bg-emerald-50 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-emerald-700">{r("Evidence for", "شواهد مؤید")}</p>
          <EvidenceList claimId={claimId} items={row.evidence_for} empty={r("No supporting evidence recorded.", "شواهد مؤیدی ثبت نشده است.")} locale={locale} />
        </div>
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-slate-600">{r("Evidence against / counter-evidence", "شواهد مخالف / متقابل")}</p>
          <EvidenceList claimId={claimId} items={row.evidence_against} empty={r("No counter-evidence recorded.", "شواهد مخالفی ثبت نشده است.")} locale={locale} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-amber-700">{r("Unknown / missing", "نامشخص / مفقود")}</p>
          <ul className="mt-2 space-y-1 text-sm text-slate-700" dir="auto">
            {row.unknown_or_missing.length
              ? row.unknown_or_missing.map((item) => <li key={item}>• {item}</li>)
              : <li>• {r("No material unknowns recorded.", "مورد نامشخص بااهمیتی ثبت نشده است.")}</li>}
          </ul>
        </div>
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-cyan-700">{r("Recommended follow-up", "پیگیری پیشنهادی")}</p>
          <ul className="mt-2 space-y-1 text-sm text-slate-700" dir="auto">
            {row.recommended_follow_up.length
              ? row.recommended_follow_up.map((item) => <li key={item}>• {item}</li>)
              : <li>• {r("No system-generated follow-up recorded.", "پیگیری سیستمی ثبت نشده است.")}</li>}
          </ul>
        </div>
      </div>

      <div className="mt-5 border-t border-slate-200 pt-4">
        {historyLoading ? (
          <p className="text-xs text-slate-500">{r("Loading decision history…", "در حال بارگذاری تاریخچه تصمیم…")}</p>
        ) : historyError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700" role="alert">
            <p dir="auto">{historyError}</p>
            <button className="secondary-button mt-2" onClick={() => void loadHistory()}>{r("Retry history", "تلاش دوباره برای تاریخچه")}</button>
          </div>
        ) : history?.items.length ? (
          <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-slate-700">
              {r(`Decision history (${history.items.length})`, `تاریخچه تصمیم (${history.items.length})`)}
            </summary>
            <div className="mt-3 space-y-3">
              {[...history.items].reverse().map((decision) => (
                <div className="border-t border-slate-200 pt-3 text-xs text-slate-600 first:border-0 first:pt-0" key={decision.id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-800">#{decision.decision_number}</span>
                    <span>{actionLabel(locale, decision.action)}</span>
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
          <p className="text-xs text-slate-400">{r("No prior human technical decisions.", "تصمیم فنی انسانی قبلی وجود ندارد.")}</p>
        )}
      </div>

      {!stateAvailable ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {r("Current evidence-state token is unavailable. Review is disabled until the page is refreshed.", "توکن وضعیت فعلی شواهد در دسترس نیست. تا تازه‌سازی صفحه، بازبینی غیرفعال است.")}
        </div>
      ) : null}

      {localError ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700" role="alert" dir="auto">{localError}</div>
      ) : null}

      {localStale ? (
        <button className="secondary-button mt-3" disabled={busy} onClick={refreshCurrentState}>
          {r("Refresh current evidence state", "تازه‌سازی وضعیت فعلی شواهد")}
        </button>
      ) : null}

      {hasPriorDecision && !reReview ? (
        <button
          className="secondary-button mt-4"
          disabled={busy || !stateAvailable || localStale}
          onClick={() => { setReReview(true); setLocalError(""); }}
        >
          {r("Start deliberate re-review", "شروع بازبینی مجدد آگاهانه")}
        </button>
      ) : null}

      {reReview ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
          {r(
            "You are deliberately re-reviewing a topic with prior human lineage. A new decision will be appended; prior decisions will not be overwritten. This remains an investigation disposition, not a causation, coverage or liability determination.",
            "شما موضوعی را که سابقه تصمیم انسانی دارد به‌طور آگاهانه دوباره بازبینی می‌کنید. تصمیم جدید به تاریخچه افزوده می‌شود و تصمیم‌های قبلی بازنویسی نمی‌شوند. این فقط تصمیم تحقیقاتی است و تعیین علت، پوشش یا مسئولیت نیست.",
          )}
        </div>
      ) : null}

      {canReview ? (
        <div className="mt-4">
          <label className="text-xs font-semibold text-slate-700" htmlFor={`technical-note-${row.key}`}>
            {r("Human review note", "یادداشت بازبینی انسانی")}
          </label>
          <textarea
            className="field mt-2 min-h-24"
            dir="auto"
            disabled={busy || localStale}
            id={`technical-note-${row.key}`}
            onChange={(event) => setNote(event.target.value)}
            placeholder={r("Explain what the current evidence supports, does not support, or still requires.", "توضیح دهید شواهد فعلی چه چیزی را پشتیبانی می‌کند، چه چیزی را پشتیبانی نمی‌کند یا چه چیزی هنوز لازم است.")}
            value={note}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="secondary-button" disabled={busy || !stateAvailable || localStale} onClick={() => submit("keep_open")}>{actionLabel(locale, "keep_open")}</button>
            <button className="secondary-button" disabled={busy || !stateAvailable || localStale} onClick={() => submit("supported_for_investigation")}>{actionLabel(locale, "supported_for_investigation")}</button>
            <button className="secondary-button" disabled={busy || !stateAvailable || localStale} onClick={() => submit("not_supported")}>{actionLabel(locale, "not_supported")}</button>
            <button className="secondary-button" disabled={busy || !stateAvailable || localStale} onClick={() => submit("needs_more_evidence")}>{actionLabel(locale, "needs_more_evidence")}</button>
            {reReview ? (
              <button className="secondary-button" disabled={busy} onClick={() => { setReReview(false); setLocalError(""); }}>
                {r("Cancel re-review", "لغو بازبینی مجدد")}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      <p className="mt-4 text-[11px] leading-5 text-slate-400">
        {r(
          "Human technical dispositions guide investigation only. They do not autonomously determine proximate cause, coverage, liability, negligence, unseaworthiness, workmanship responsibility, fraud, reserve, settlement, payment or recovery.",
          "تصمیم‌های فنی انسانی فقط تحقیق را هدایت می‌کنند و به‌طور خودکار علت مؤثر، پوشش، مسئولیت، تقصیر، عدم قابلیت دریانوردی، مسئولیت ناشی از کیفیت کار، تقلب، ذخیره خسارت، سازش، پرداخت یا بازیافت را تعیین نمی‌کنند.",
        )}
      </p>
    </article>
  );
}
