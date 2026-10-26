"use client";

import { useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import {
  listOcrSourceDiscrepancies,
  reportOcrSourceDiscrepancy,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { evidenceT, type EvidenceKey } from "@/lib/i18n-evidence";
import type {
  ClaimDocument,
  OcrDiscrepancyKind,
  OcrDiscrepancyReceipt,
  SourceExtractionSegmentsResponse,
} from "@/lib/types";

const KINDS: OcrDiscrepancyKind[] = [
  "negation_missing",
  "negation_scope_changed",
  "date_time_changed",
  "technical_term_changed",
  "other_transcription_discrepancy",
];

type Props = {
  claimId: string;
  document: ClaimDocument;
  source: SourceExtractionSegmentsResponse;
};

/** Read-only OCR source + separately append-only operator observations. */
export function OcrDiscrepancyWorkspace({ claimId, document, source }: Props) {
  const { locale } = useLocale();
  const t = (key: EvidenceKey, values?: Record<string, string | number>) =>
    evidenceT(locale, key, values);
  const [showForm, setShowForm] = useState(false);
  const [selected, setSelected] = useState("");
  const [kind, setKind] = useState<OcrDiscrepancyKind>("negation_missing");
  const [compared, setCompared] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const [saved, setSaved] = useState<OcrDiscrepancyReceipt | null>(null);
  const [history, setHistory] = useState<OcrDiscrepancyReceipt[] | null>(null);
  const [historyError, setHistoryError] = useState(false);

  async function refreshHistory() {
    try {
      const data = await listOcrSourceDiscrepancies(claimId, document.id);
      // A historic observation may refer to an earlier extraction, so
      // display report state and version without implying current validity.
      setHistory(data.items.filter((r) =>
        r.document_id === document.id &&
        r.review_state === "reported_unverified" &&
        r.claim_fact_approved === false
      ));
      setHistoryError(false);
    } catch {
      setHistoryError(true);
    }
  }

  useEffect(() => {
    let live = true;
    void listOcrSourceDiscrepancies(claimId, document.id).then(
      (data) => {
        if (!live) return;
        setHistory(data.items.filter((r) =>
          r.document_id === document.id &&
          r.review_state === "reported_unverified" &&
          r.claim_fact_approved === false
        ));
        setHistoryError(false);
      },
      () => { if (live) setHistoryError(true); },
    );
    return () => { live = false; };
  }, [claimId, document.id]);

  const eligible = source.segments.filter((segment) => !segment.text_truncated);
  const selectedRow = eligible.find((segment) => String(segment.segment_index) === selected);
  const sourceMatched = (
    source.document_id === document.id &&
    source.document_version === document.version_number &&
    source.source_file_hash === document.file_hash &&
    source.review_disposition === "machine_unverified" &&
    source.source_text_quality_state === "ocr_human_source_comparison_required" &&
    typeof source.extraction_text_hash === "string" &&
    source.extraction_text_hash.length === 64
  );

  async function submitReport() {
    if (!sourceMatched || !selectedRow || !compared || saving) return;
    setSaving(true);
    setError(false);
    setSaved(null);
    try {
      const receipt = await reportOcrSourceDiscrepancy(claimId, document.id, {
        document_version: source.document_version,
        source_file_hash: source.source_file_hash,
        extraction_text_hash: source.extraction_text_hash!,
        segment_index: selectedRow.segment_index,
        issue_kind: kind,
        source_compared_by_operator: true,
      });
      if (
        receipt.document_id !== document.id ||
        receipt.document_version !== source.document_version ||
        receipt.source_file_hash !== source.source_file_hash ||
        receipt.extraction_text_hash !== source.extraction_text_hash ||
        receipt.segment_index !== selectedRow.segment_index ||
        receipt.issue_kind !== kind ||
        receipt.review_state !== "reported_unverified" ||
        receipt.claim_fact_approved !== false
      ) {
        setError(true);
        return;
      }
      setSaved(receipt);
      setShowForm(false);
      setCompared(false);
      setSelected("");
      void refreshHistory();
    } catch {
      setError(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-4 border-t border-slate-200 pt-4" data-testid="ocr-discrepancy-workspace">
      <h4 className="font-semibold text-slate-900">{t("ocrIssue.title")}</h4>
      <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-700">
        {t("ocrIssue.help")}
      </p>
      {eligible.length === 0 ? (
        <p className="mt-2 text-xs font-semibold text-amber-800">
          {t("ocrIssue.truncated")}
        </p>
      ) : null}
      {!showForm && sourceMatched && eligible.length > 0 ? (
        <button
          type="button"
          className="mt-3 text-sm font-semibold text-amber-800 underline"
          onClick={() => { setShowForm(true); setSaved(null); setError(false); }}
        >{t("ocrIssue.open")}</button>
      ) : null}

      {showForm && sourceMatched ? (
        <div className="mt-3 max-w-xl rounded-lg border border-amber-200 bg-amber-50/50 p-3">
          <label className="block text-sm font-semibold text-slate-800" htmlFor="ocr-report-segment">
            {t("ocrIssue.segment")}
          </label>
          <select
            id="ocr-report-segment"
            data-testid="ocr-report-segment"
            value={selected}
            onChange={(e) => { setSelected(e.target.value); setCompared(false); }}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 text-sm"
          >
            <option value="">—</option>
            {eligible.map((segment) => (
              <option key={segment.segment_index} value={segment.segment_index}>
                {segment.locator_type} {segment.locator_value} · #{segment.segment_index + 1}
              </option>
            ))}
          </select>
          <label className="mt-3 block text-sm font-semibold text-slate-800" htmlFor="ocr-report-kind">
            {t("ocrIssue.kind")}
          </label>
          <select
            id="ocr-report-kind"
            data-testid="ocr-report-kind"
            value={kind}
            onChange={(e) => { setKind(e.target.value as OcrDiscrepancyKind); setCompared(false); }}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 text-sm"
          >
            {KINDS.map((value) => (
              <option value={value} key={value}>
                {t(`ocrIssue.${value}` as EvidenceKey)}
              </option>
            ))}
          </select>
          <label className="mt-3 flex gap-2 text-sm text-slate-800">
            <input
              type="checkbox"
              checked={compared}
              onChange={(e) => setCompared(e.target.checked)}
              data-testid="ocr-report-attestation"
              className="mt-1"
            />
            <span>{t("ocrIssue.attestation")}</span>
          </label>
          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="button"
              data-testid="ocr-report-submit"
              disabled={!selectedRow || !compared || saving}
              onClick={() => void submitReport()}
              className="rounded-md bg-amber-800 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
            >{saving ? t("ocrIssue.saving") : t("ocrIssue.submit")}</button>
            <button
              type="button"
              disabled={saving}
              onClick={() => { setShowForm(false); setSelected(""); setCompared(false); setError(false); }}
              className="text-sm font-semibold text-slate-700 underline"
            >{t("ocrIssue.cancel")}</button>
          </div>
        </div>
      ) : null}

      {saved ? (
        <p role="status" data-testid="ocr-report-receipt" className="mt-3 text-sm text-slate-700">
          {t("ocrIssue.saved")} <code dir="ltr">{saved.id}</code>
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-sm font-semibold text-red-700">{t("ocrIssue.error")}</p>
      ) : null}

      <div className="mt-4">
        <p className="text-sm font-semibold text-slate-800">{t("ocrIssue.history")}</p>
        {historyError ? (
          <p role="note" className="mt-1 text-xs text-red-700">{t("ocrIssue.historyFailed")}</p>
        ) : history === null ? null : history.length === 0 ? (
          <p className="mt-1 text-xs text-slate-600">{t("ocrIssue.historyEmpty")}</p>
        ) : (
          <ul className="mt-2 space-y-2 text-xs text-slate-700">
            {history.map((receipt) => (
              <li key={receipt.id} className="rounded-md border border-slate-200 p-2">
                {t("ocrIssue.record", {
                  kind: t(`ocrIssue.${receipt.issue_kind}` as EvidenceKey),
                  version: receipt.document_version,
                  segment: receipt.segment_index + 1,
                  time: formatDateTime(receipt.reported_at, locale),
                })}
                <span className="ms-2 font-semibold text-amber-900">
                  {t("ocrIssue.unverified")}
                </span>
              </li>
            ))}
          </ul>
        )}
        {history !== null && history.length >= 25 ? (
          <p className="mt-2 text-xs text-slate-600">{t("ocrIssue.historyLimited")}</p>
        ) : null}
      </div>
    </section>
  );
}
