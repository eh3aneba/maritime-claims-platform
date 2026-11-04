"use client";

import { useEffect, useState } from "react";
import { useLocale } from "@/components/locale-provider";
import { getOcrReviewWorkpaperBinding, listIndependentOcrReviews } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import {
  parseOcrReviewReadback, parseOcrWorkpaperReadback,
  type OcrReviewReadback, type WorkpaperReadback,
} from "@/lib/ocr-review-readback";
import type { OcrDiscrepancyReceipt } from "@/lib/types";

type Props = { claimId: string; report: OcrDiscrepancyReceipt; currentSource: boolean };

function WorkpaperBinding({ claimId, report, review }: Omit<Props, "currentSource"> & { review: OcrReviewReadback }) {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => locale === "fa" ? fa : en;
  const [open, setOpen] = useState(false);
  const [binding, setBinding] = useState<WorkpaperReadback | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setBinding(null); setFailed(false);
    void getOcrReviewWorkpaperBinding(claimId, report.document_id, report.id, review.id)
      .then((data) => { const row = parseOcrWorkpaperReadback(data, report, review); if (active) setBinding(row); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [open, claimId, report, review]);
  return <div className="mt-2">
    <button type="button" className="font-semibold text-cyan-800 underline" onClick={() => setOpen(!open)} aria-expanded={open}>
      {L("Managed workpaper record", "سابقهٔ کاربرگ مدیریت‌شده")}
    </button>
    {open && failed ? <p role="alert">{L("No matching accessible binding could be verified. This does not prove that no workpaper exists.", "پیوند منطبق و قابل دسترس تأیید نشد؛ این به معنی نبود کاربرگ نیست.")}</p> : null}
    {open && !failed && !binding ? <p role="status">{L("Loading record…", "در حال دریافت سابقه…")}</p> : null}
    {open && binding ? <div data-testid="ocr-workpaper-record" className="mt-2 break-all">
      <p>{L("Recorded document", "سند ثبت‌شده")}: <code dir="ltr">{binding.workpaper_document_id} · v{binding.workpaper_document_version}</code></p>
      <p dir="ltr">SHA-256 {binding.workpaper_file_hash}</p>
      <p>{L("Historical metadata linkage only. Current file availability, bytes and workpaper content have not been verified by this view.", "فقط پیوند تاریخی فراداده است؛ دسترسی فعلی، بایت‌ها و محتوای کاربرگ در این نما بررسی نشده‌اند.")}</p>
    </div> : null}
  </div>;
}

/** Read-only visibility of existing assertions; never records or grants acceptance. */
export function OcrIndependentReviewHistory({ claimId, report, currentSource }: Props) {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => locale === "fa" ? fa : en;
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<OcrReviewReadback[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!open || !currentSource) return;
    let active = true;
    setItems(null); setFailed(false);
    void listIndependentOcrReviews(claimId, report.document_id, report.id)
      .then((data) => { const rows = parseOcrReviewReadback(data, report); if (active) setItems(rows); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [open, currentSource, claimId, report]);
  if (!currentSource) return <p className="mt-2 text-amber-900">{L("Historical source: reload the matching source before inspecting independent reviews.", "منبع تاریخی است؛ برای مشاهدهٔ بازبینی مستقل، منبع منطبق را دوباره بارگذاری کنید.")}</p>;
  const outcomes = {
    discrepancy_observed: L("Discrepancy observed", "اختلاف مشاهده شد"),
    not_reproduced: L("Not reproduced", "بازتولید نشد"),
    inconclusive: L("Inconclusive", "نتیجه نامشخص"),
  };
  return <div className="mt-2" data-testid="ocr-independent-history">
    <button type="button" className="font-semibold text-cyan-800 underline" aria-expanded={open} onClick={() => setOpen(!open)}>
      {L("Independent review history", "سوابق بازبینی مستقل")}
    </button>
    {open ? <div className="mt-2">
      <p role="note" className="font-semibold text-amber-900">{L("Recorded observations only; no source hold cleared, Claim Fact approved or independent acceptance established by this screen.", "فقط مشاهدات ثبت‌شده است؛ این صفحه قفل منبع را رفع نمی‌کند و واقعیت پرونده یا پذیرش مستقل را تأیید نمی‌کند.")}</p>
      {failed ? <p role="alert">{L("Review history is unavailable or no longer matches this source. Do not interpret this as no reviews.", "سوابق بازبینی در دسترس نیست یا با این منبع منطبق نیست؛ این به معنی نبود بازبینی نیست.")}</p> : items === null ? <p role="status">{L("Loading observations…", "در حال دریافت مشاهدات…")}</p> : items.length === 0 ? <p>{L("No observations in this page; independent acceptance remains unverified.", "در این صفحه مشاهده‌ای ثبت نشده است؛ پذیرش مستقل همچنان تأیید نشده است.")}</p> : <ul className="space-y-3">
        {items.map((review) => <li key={review.id} className="mt-2 border-s-2 border-amber-300 ps-3" data-testid="ocr-independent-observation">
          <p>{outcomes[review.outcome]} · {formatDateTime(review.reviewed_at, locale)}</p>
          <p>{L("Observation reference", "شناسهٔ مشاهده")}: <code dir="ltr">{review.id}</code></p>
          <p className="break-all" dir="ltr">SHA-256 {review.review_workpaper_sha256}</p>
          <WorkpaperBinding claimId={claimId} report={report} review={review} />
        </li>)}
      </ul>}
      {items?.length === 25 ? <p>{L("Most recent 25 only; additional observations may exist.", "فقط ۲۵ مشاهدهٔ اخیر؛ ممکن است سوابق بیشتری وجود داشته باشد.")}</p> : null}
    </div> : null}
  </div>;
}
