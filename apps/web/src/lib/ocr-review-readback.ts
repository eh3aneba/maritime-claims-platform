import type { OcrDiscrepancyReceipt } from "./types";

type RecordValue = Record<string, unknown>;
export type OcrReviewReadback = {
  id: string;
  reviewed_at: string;
  outcome: "discrepancy_observed" | "not_reproduced" | "inconclusive";
  review_workpaper_sha256: string;
};
export type WorkpaperReadback = {
  workpaper_document_id: string;
  workpaper_document_version: number;
  workpaper_file_hash: string;
};
function record(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Invalid OCR readback");
  return value as RecordValue;
}
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);

/** Reject the whole page on a mismatched row; never silently show a partial history. */
export function parseOcrReviewReadback(value: unknown, report: OcrDiscrepancyReceipt): OcrReviewReadback[] {
  const page = record(value);
  if (page.offset !== 0 || page.limit !== 25 || !Array.isArray(page.items) || page.items.length > 25) {
    throw Error("Invalid OCR review page");
  }
  const seen = new Set<string>();
  return page.items.map((value) => {
    const r = record(value);
    if (
      !uuid(r.id) || seen.has(r.id) || !uuid(r.reviewed_by_id) ||
      r.reviewed_by_id === report.reported_by_id ||
      r.report_id !== report.id || r.document_id !== report.document_id ||
      !hash(r.source_file_hash) || r.source_file_hash !== report.source_file_hash ||
      !hash(r.extraction_text_hash) || r.extraction_text_hash !== report.extraction_text_hash ||
      !hash(r.review_workpaper_sha256) ||
      typeof r.reviewed_at !== "string" || !Number.isFinite(Date.parse(r.reviewed_at)) ||
      !["discrepancy_observed", "not_reproduced", "inconclusive"].includes(String(r.outcome)) ||
      r.review_method !== "visual_original_scan" ||
      r.review_state !== "independent_observation_no_clearance" ||
      r.source_hold_cleared !== false || r.claim_fact_approved !== false
    ) throw Error("OCR review does not match source");
    seen.add(r.id);
    return r as unknown as OcrReviewReadback;
  });
}

export function parseOcrWorkpaperReadback(
  value: unknown, report: OcrDiscrepancyReceipt, review: OcrReviewReadback,
): WorkpaperReadback {
  const r = record(value);
  if (
    !uuid(r.id) || r.report_id !== report.id || r.review_id !== review.id ||
    r.document_id !== report.document_id || !uuid(r.workpaper_document_id) ||
    r.workpaper_document_id === report.document_id ||
    !Number.isSafeInteger(r.workpaper_document_version) || Number(r.workpaper_document_version) < 1 ||
    !hash(r.workpaper_file_hash) || r.workpaper_file_hash !== review.review_workpaper_sha256 ||
    r.custody_state !== "managed_clean_document_record_linked" ||
    r.original_source_hold_cleared !== false || r.claim_fact_approved !== false
  ) throw Error("Workpaper binding does not match review");
  return r as unknown as WorkpaperReadback;
}
