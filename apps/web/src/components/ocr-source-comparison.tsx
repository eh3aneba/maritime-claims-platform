"use client";

import { useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { downloadClaimDocument, getUnverifiedSourceSegments } from "@/lib/api";
import { evidenceT } from "@/lib/i18n-evidence";
import type { ClaimDocument, SourceExtractionSegmentsResponse } from "@/lib/types";

type Props = {
  claimId: string;
  document: ClaimDocument;
  expectedExtractionHash: string | null;
  onClose: () => void;
};

const PAGE_SIZE = 5;
const MAX_OFFSET = 10_000;

/** An on-demand review aid. This never records a human check or approval. */
export function OcrSourceComparison({
  claimId, document, expectedExtractionHash, onClose,
}: Props) {
  const { locale } = useLocale();
  const t = (key: Parameters<typeof evidenceT>[1], values?: Record<string, string | number>) =>
    evidenceT(locale, key, values);
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState<SourceExtractionSegmentsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [downloadError, setDownloadError] = useState(false);

  useEffect(() => {
    let active = true;
    setSource(null);
    setLoadError(false);
    setLoading(true);
    void getUnverifiedSourceSegments(claimId, document.id, offset)
      .then((data) => {
        if (!active) return;
        // Never show stale, substituted, or non-OCR text as this source.
        if (
          data.document_id !== document.id ||
          data.document_version !== document.version_number ||
          data.source_file_hash !== document.file_hash ||
          !expectedExtractionHash ||
          data.extraction_text_hash !== expectedExtractionHash ||
          data.review_disposition !== "machine_unverified" ||
          data.source_text_quality_state !== "ocr_human_source_comparison_required" ||
          !data.extraction_method.toLowerCase().includes("tesseract:") ||
          data.offset !== offset || data.limit !== PAGE_SIZE
        ) {
          setLoadError(true);
          return;
        }
        setSource(data);
      })
      .catch(() => { if (active) setLoadError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [claimId, document.id, document.file_hash, document.version_number, expectedExtractionHash, offset]);

  async function downloadOriginal() {
    setDownloadError(false);
    try {
      await downloadClaimDocument(claimId, document);
    } catch {
      setDownloadError(true);
    }
  }

  return (
    <section
      data-testid={`ocr-comparison-${document.id}`}
      aria-label={t("ocrPreview.title")}
      className="mt-5 rounded-xl border border-amber-300 bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{t("ocrPreview.title")}</h3>
          <p className="mt-1 max-w-3xl text-sm text-amber-900">{t("ocrPreview.help")}</p>
          <p className="mt-2 font-semibold text-xs text-red-800" role="note">
            {t("ocrPreview.notVerified")}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => void downloadOriginal()}
            className="text-sm font-semibold text-cyan-800 underline"
          >{t("ocrPreview.download")}</button>
          <button
            type="button"
            onClick={onClose}
            className="text-sm font-semibold text-slate-700 underline"
          >{t("ocrPreview.close")}</button>
        </div>
      </div>
      {downloadError ? <p role="alert" className="mt-3 text-sm text-red-700">{t("download.failed")}</p> : null}
      <p className="mt-3 break-all font-mono text-xs text-slate-500" dir="ltr">
        v{document.version_number} · SHA-256 {document.file_hash.slice(0, 12)}…
      </p>

      {loading ? <p role="status" className="mt-4 text-sm text-slate-600">{t("ocrPreview.loading")}</p> : null}
      {!loading && loadError ? (
        <p role="alert" className="mt-4 text-sm font-semibold text-red-700">{t("ocrPreview.error")}</p>
      ) : null}

      {!loading && source ? (
        <>
          <p className="mt-3 text-xs text-slate-600">{t("ocrPreview.hash")}</p>
          <div className="mt-3 space-y-3">
            {source.segments.length === 0 ? (
              <p className="text-sm text-amber-900">{t("ocrPreview.empty")}</p>
            ) : source.segments.map((segment) => (
              <div key={segment.segment_index} className="rounded-lg border border-slate-200 p-3">
                <p className="mb-2 text-xs font-semibold text-slate-600">
                  {t("ocrPreview.page", {
                    locatorType: segment.locator_type,
                    locatorValue: segment.locator_value,
                    index: segment.segment_index + 1,
                  })}
                </p>
                <pre
                  data-testid={`ocr-transcript-segment-${segment.segment_index}`}
                  dir="auto"
                  className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-sm leading-7 text-slate-900"
                >{segment.text_preview}</pre>
                {segment.text_truncated ? (
                  <p role="note" className="mt-2 text-xs font-semibold text-red-700">
                    {t("ocrPreview.truncated", {
                      shown: segment.text_preview.length,
                      total: segment.source_char_count,
                    })}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-slate-600">
              {t("ocrPreview.count", {
                start: source.total_segments ? source.offset + 1 : 0,
                end: Math.min(source.offset + source.segments.length, source.total_segments),
                total: source.total_segments,
              })}
            </span>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((x) => Math.max(0, x - PAGE_SIZE))}
                className="font-semibold text-cyan-800 disabled:opacity-40"
              >{t("ocrPreview.previous")}</button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= source.total_segments || offset + PAGE_SIZE > MAX_OFFSET}
                onClick={() => setOffset((x) => Math.min(MAX_OFFSET, x + PAGE_SIZE))}
                className="font-semibold text-cyan-800 disabled:opacity-40"
              >{t("ocrPreview.next")}</button>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
