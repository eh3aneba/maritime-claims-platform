"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim, getCurrentUser } from "@/lib/api";
import {
  createClaimCorrespondence,
  listClaimCorrespondence,
  markClaimCorrespondenceSent,
  reviewClaimCorrespondence,
  reviseClaimCorrespondence,
  submitClaimCorrespondence,
  updateClaimCorrespondence,
  type GovernedClaimCorrespondence,
} from "@/lib/correspondence-maturity-api";
import { formatDate } from "@/lib/format";
import {
  correspondenceChannelLabel,
  correspondenceDirectionLabel,
  correspondenceDirectionOptionLabel,
  correspondenceKindLabel,
  correspondenceKindOptionLabel,
  correspondenceReviewActionLabel,
  correspondenceReviewStateLabel,
  correspondenceSensitivityLabel,
  correspondenceStatusLabel,
  correspondenceT,
} from "@/lib/i18n-correspondence-export";
import type {
  Claim,
  CorrespondenceChannel,
  CorrespondenceDirection,
  CorrespondenceKind,
  CorrespondenceSensitivity,
  CurrentUser,
} from "@/lib/types";

const statusTone: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  rejected: "bg-red-50 text-red-700",
  under_review: "bg-amber-50 text-amber-800",
  approved: "bg-violet-50 text-violet-700",
  sent_externally: "bg-emerald-50 text-emerald-700",
  received_external: "bg-cyan-50 text-cyan-700",
  filed_internal: "bg-blue-50 text-blue-700",
};

const reviewTone: Record<string, string> = {
  none: "border-slate-200 bg-slate-50 text-slate-700",
  current: "border-emerald-200 bg-emerald-50 text-emerald-800",
  stale: "border-amber-200 bg-amber-50 text-amber-900",
  legacy_unbound: "border-orange-200 bg-orange-50 text-orange-900",
};

// This is authored correspondence content, not UI copy. It intentionally remains English
// when the operator changes locale and is never machine-translated.
const initialForm = {
  direction: "outbound" as CorrespondenceDirection,
  kind: "general" as CorrespondenceKind,
  sensitivity: "standard" as CorrespondenceSensitivity,
  sender_label: "",
  recipient_label: "Shipowner / Assured",
  subject: "",
  body: "Dear Sirs,\n\nFurther to the above matter, please find our factual update for your review. Any options remain subject to factual, technical and insurance assessment and, where appropriate, joint discussion.\n\nKind regards,",
  channel: "email" as CorrespondenceChannel,
  external_reference: "",
};

export default function CorrespondenceCentrePage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const c = (en: string, fa: string) => correspondenceT(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [items, setItems] = useState<GovernedClaimCorrespondence[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState(initialForm);
  const [reviewNote, setReviewNote] = useState("");
  const [dispatchReference, setDispatchReference] = useState("");
  const [dispatchChannel, setDispatchChannel] = useState<CorrespondenceChannel>("email");
  const [confirmSent, setConfirmSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const selected = useMemo(() => items.find((item) => item.id === selectedId) ?? null, [items, selectedId]);
  const canReview = user?.role === "admin" || user?.role === "claims_manager";

  async function load(preferId?: string) {
    try {
      const [claimData, userData, correspondence] = await Promise.all([
        getClaim(id),
        getCurrentUser(),
        listClaimCorrespondence(id),
      ]);
      setClaim(claimData);
      setUser(userData);
      setItems(correspondence.items);
      setSelectedId(preferId ?? selectedId ?? correspondence.items[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : c("Correspondence Centre could not be loaded.", "مرکز مکاتبات قابل بارگذاری نیست."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [id]);

  async function recoverConflict(e: unknown, selectedItem?: GovernedClaimCorrespondence | null) {
    if (e instanceof ApiError && e.status === 409) {
      setError(c(
        "This view was stale or the governed state changed. The current server state has been reloaded; review it before continuing.",
        "این نما قدیمی بود یا وضعیت کنترل‌شده تغییر کرده است. وضعیت فعلی سرور دوباره بارگذاری شد؛ پیش از ادامه آن را بازبینی کنید.",
      ));
      await load(selectedItem?.id);
      return;
    }
    setError(e instanceof ApiError ? e.detail : c("Correspondence state could not be updated.", "وضعیت مکاتبه به‌روزرسانی نشد."));
  }

  async function createItem() {
    setBusy(true); setError("");
    try {
      const item = await createClaimCorrespondence(id, {
        direction: form.direction,
        kind: form.kind,
        sensitivity: form.sensitivity,
        sender_label: form.sender_label.trim() || null,
        recipient_label: form.recipient_label.trim() || null,
        subject: form.subject.trim(),
        body: form.body.trim(),
        channel: form.direction === "outbound" ? null : form.channel,
        external_reference: form.external_reference.trim() || null,
      });
      setForm(initialForm);
      await load(item.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : c("Correspondence could not be created.", "مکاتبه ایجاد نشد."));
    } finally {
      setBusy(false);
    }
  }

  async function persistDraft(item: GovernedClaimCorrespondence) {
    return updateClaimCorrespondence(id, item, {
      sensitivity: item.sensitivity,
      recipient_label: item.recipient_label,
      subject: item.subject,
      body: item.body,
    });
  }

  async function saveDraft() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await persistDraft(selected);
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) {
      await recoverConflict(e, selected);
    } finally {
      setBusy(false);
    }
  }

  function patchSelected(patch: Partial<GovernedClaimCorrespondence>) {
    if (!selected) return;
    setItems((current) => current.map((item) => item.id === selected.id ? { ...item, ...patch } : item));
  }

  async function transition(action: "submit" | "approve" | "reject") {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      let updated: GovernedClaimCorrespondence;
      if (action === "submit") {
        // Persist the visible draft first, still bound to the state fingerprint the operator loaded.
        // This prevents unsaved local wording from being silently skipped when review is requested.
        const prepared = await persistDraft(selected);
        updated = await submitClaimCorrespondence(id, prepared);
      } else {
        updated = await reviewClaimCorrespondence(id, selected, action, reviewNote.trim());
      }
      setReviewNote("");
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) {
      await recoverConflict(e, selected);
    } finally {
      setBusy(false);
    }
  }

  async function reopenForRevision() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await reviseClaimCorrespondence(id, selected);
      setConfirmSent(false);
      setDispatchReference("");
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) {
      await recoverConflict(e, selected);
    } finally {
      setBusy(false);
    }
  }

  async function resubmitRequestContext() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await submitClaimCorrespondence(id, selected);
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) {
      await recoverConflict(e, selected);
    } finally {
      setBusy(false);
    }
  }

  async function markSent() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await markClaimCorrespondenceSent(id, selected, {
        confirm_sent: confirmSent,
        channel: dispatchChannel,
        external_reference: dispatchReference.trim() || null,
      });
      setConfirmSent(false);
      setDispatchReference("");
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) {
      await recoverConflict(e, selected);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">{c("Loading correspondence…", "در حال بارگذاری مکاتبات…")}</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || c("Claim unavailable.", "پرونده در دسترس نیست.")}</div>;

  const requestContextNeedsReview = Boolean(
    selected?.request_batch_id
    && selected.status === "approved"
    && ["stale", "legacy_unbound"].includes(selected.review_state),
  );

  return <div>
    <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">
      {locale === "fa" ? "→" : "←"} {c(`Back to ${claim.vessel.name}`, `بازگشت به ${claim.vessel.name}`)}
    </Link>
    <div className="mt-5">
      <p className="eyebrow" dir="ltr">{claim.claim_reference}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{c("Correspondence Centre", "مرکز مکاتبات")}</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
        {c(
          "Draft, review and file claim communications with an audit trail. This centre does not send email or connect to a mailbox; “Sent Externally” only records a dispatch completed outside the platform.",
          "مکاتبات پرونده را با ردپای حسابرسی پیش‌نویس، بازبینی و ثبت کنید. این مرکز ایمیل ارسال نمی‌کند و به صندوق پستی متصل نیست؛ «ثبت ارسال خارجی» فقط ارسالی را ثبت می‌کند که خارج از پلتفرم انجام شده است.",
        )}
      </p>
    </div>

    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

    <section className="panel mt-6 p-6">
      <div>
        <h2 className="section-title">{c("Create correspondence", "ایجاد مکاتبه")}</h2>
        <p className="section-subtitle">{c("Outbound items begin as editable drafts. Inbound and internal items are filed immediately as manual records.", "موارد خروجی به‌صورت پیش‌نویس قابل ویرایش آغاز می‌شوند. موارد ورودی و داخلی بلافاصله به‌عنوان رکورد دستی ثبت می‌شوند.")}</p>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <label><span className="label">{c("Direction", "جهت")}</span><select className="field" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as CorrespondenceDirection })}><option value="outbound">{correspondenceDirectionOptionLabel(locale, "outbound")}</option><option value="inbound">{correspondenceDirectionOptionLabel(locale, "inbound")}</option><option value="internal">{correspondenceDirectionOptionLabel(locale, "internal")}</option></select></label>
        <label><span className="label">{c("Type", "نوع")}</span><select className="field" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as CorrespondenceKind })}><option value="general">{correspondenceKindOptionLabel(locale, "general")}</option><option value="follow_up">{correspondenceKindOptionLabel(locale, "follow_up")}</option><option value="status_update">{correspondenceKindOptionLabel(locale, "status_update")}</option><option value="reservation_of_rights">{correspondenceKindOptionLabel(locale, "reservation_of_rights")}</option><option value="settlement">{correspondenceKindOptionLabel(locale, "settlement")}</option></select></label>
        <label><span className="label">{c("Sensitivity", "حساسیت")}</span><select className="field" value={form.sensitivity} onChange={(e) => setForm({ ...form, sensitivity: e.target.value as CorrespondenceSensitivity })}>{(["standard", "confidential", "privileged_confidential", "without_prejudice"] as CorrespondenceSensitivity[]).map((value) => <option key={value} value={value}>{correspondenceSensitivityLabel(locale, value)}</option>)}</select></label>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {form.direction === "inbound" ? <label><span className="label">{c("Sender", "فرستنده")}</span><input className="field" dir="auto" value={form.sender_label} onChange={(e) => setForm({ ...form, sender_label: e.target.value })} placeholder={c("e.g. Average Adjuster", "مثلاً Average Adjuster")} /></label> : null}
        {form.direction === "outbound" ? <label><span className="label">{c("Recipient", "گیرنده")}</span><input className="field" dir="auto" value={form.recipient_label} onChange={(e) => setForm({ ...form, recipient_label: e.target.value })} /></label> : null}
        <label><span className="label">{c("Subject", "موضوع")}</span><input className="field" dir="auto" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder={`${claim.claim_reference} – Status update`} /></label>
      </div>
      <label className="mt-4 block"><span className="label">{c("Body", "متن مکاتبه")}</span><textarea className="field min-h-48 resize-y" dir="auto" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
      <button className="primary-button mt-4" disabled={busy || form.subject.trim().length < 3 || form.body.trim().length < 3} onClick={createItem}>{busy ? c("Working…", "در حال انجام…") : form.direction === "outbound" ? c("Create draft", "ایجاد پیش‌نویس") : c("File record", "ثبت رکورد")}</button>
    </section>

    <div className="mt-6 grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="panel p-4">
        <h2 className="px-2 text-sm font-semibold text-slate-950">{c("Claim correspondence", "مکاتبات پرونده")}</h2>
        <p className="px-2 text-xs text-slate-500">{locale === "fa" ? `${items.length} رکورد` : `${items.length} record(s)`}</p>
        <div className="mt-3 space-y-2">
          {items.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full rounded-xl border p-3 ${locale === "fa" ? "text-right" : "text-left"} ${item.id === selectedId ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white"}`}>
            <div className="flex items-start justify-between gap-2"><p className="line-clamp-2 text-sm font-semibold text-slate-900" dir="auto">{item.subject}</p><span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${statusTone[item.status] ?? "bg-slate-100 text-slate-700"}`}>{correspondenceStatusLabel(locale, item.status)}</span></div>
            <p className="mt-2 text-xs text-slate-500">{correspondenceDirectionLabel(locale, item.direction)} · {correspondenceSensitivityLabel(locale, item.sensitivity)}</p>
            <p className="mt-1 text-[11px] text-slate-400" dir="ltr">{formatDate(item.created_at, locale)}</p>
          </button>)}
          {!items.length ? <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">{c("No correspondence recorded.", "مکاتبه‌ای ثبت نشده است.")}</div> : null}
        </div>
      </aside>

      <section className="panel p-6">
        {!selected ? <div className="py-20 text-center text-sm text-slate-500">{c("Select a correspondence record.", "یک رکورد مکاتبه را انتخاب کنید.")}</div> : <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">{correspondenceDirectionLabel(locale, selected.direction)} · {correspondenceKindLabel(locale, selected.kind)}</p>
              <h2 className="mt-1 text-xl font-semibold text-slate-950" dir="auto">{selected.subject}</h2>
              <p className="mt-1 text-[11px] text-slate-400" dir="ltr">state v{selected.state_version} · {selected.state_fingerprint.slice(0, 12)}…</p>
            </div>
            <div className="flex flex-wrap gap-2"><span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${statusTone[selected.status] ?? "bg-slate-100 text-slate-700"}`}>{correspondenceStatusLabel(locale, selected.status)}</span><span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">{correspondenceSensitivityLabel(locale, selected.sensitivity)}</span></div>
          </div>

          <div className={`mt-4 rounded-xl border p-4 ${reviewTone[selected.review_state] ?? reviewTone.none}`} data-testid="correspondence-review-integrity">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">{c("Review integrity", "یکپارچگی بازبینی")}</p>
              <span className="rounded-full bg-white/70 px-2.5 py-1 text-xs font-semibold">{correspondenceReviewStateLabel(locale, selected.review_state)}</span>
            </div>
            <p className="mt-2 text-xs leading-5">
              {selected.review_state === "current" && c("The latest human review is bound to this exact communication state and, where applicable, the exact document-request context.", "آخرین بازبینی انسانی به همین وضعیت دقیق مکاتبه و در صورت کاربرد، به زمینه دقیق درخواست سند متصل است.")}
              {selected.review_state === "none" && c("No human review has yet been recorded for this correspondence.", "هنوز بازبینی انسانی برای این مکاتبه ثبت نشده است.")}
              {selected.review_state === "stale" && c("A historical review exists, but it does not govern the current state. Deliberate re-review is required before dispatch.", "یک بازبینی تاریخی وجود دارد، اما وضعیت فعلی را پوشش نمی‌دهد. پیش از ثبت ارسال، بازبینی مجدد آگاهانه لازم است.")}
              {selected.review_state === "legacy_unbound" && c("A historical review exists without an exact current context binding. Re-review is required before governed dispatch.", "یک بازبینی تاریخی بدون اتصال دقیق به زمینه فعلی وجود دارد. پیش از ثبت ارسال کنترل‌شده، بازبینی مجدد لازم است.")}
            </p>
            {selected.latest_review ? <div className="mt-3 grid gap-1 text-[11px] sm:grid-cols-2">
              <p><span className="font-semibold">{c("Latest review", "آخرین بازبینی")}:</span> #{selected.latest_review.review_number} · {correspondenceReviewActionLabel(locale, selected.latest_review.action)}</p>
              <p dir="ltr"><span className="font-semibold">review hash:</span> {selected.latest_review.review_hash.slice(0, 16)}…</p>
              {selected.latest_review.request_context_fingerprint ? <p className="sm:col-span-2" dir="ltr"><span className="font-semibold">request context:</span> {selected.latest_review.request_context_fingerprint.slice(0, 16)}…</p> : null}
            </div> : null}
          </div>

          {["draft", "rejected"].includes(selected.status) ? <div className="mt-5 space-y-4">
            {selected.review_history.length > 0 ? <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-xs leading-5 text-cyan-900">{c("Revision mode is open. Historical review decisions remain immutable; a material edit receives a new state identity and must be submitted for explicit re-review.", "حالت اصلاح باز است. تصمیم‌های بازبینی تاریخی تغییرناپذیر می‌مانند؛ هر تغییر محتوایی مهم هویت وضعیت جدید می‌گیرد و باید برای بازبینی مجدد صریح ارسال شود.")}</div> : null}
            <label className="block"><span className="label">{c("Recipient", "گیرنده")}</span><input className="field" dir="auto" value={selected.recipient_label ?? ""} onChange={(e) => patchSelected({ recipient_label: e.target.value })} /></label>
            <label className="block"><span className="label">{c("Subject", "موضوع")}</span><input className="field" dir="auto" value={selected.subject} onChange={(e) => patchSelected({ subject: e.target.value })} /></label>
            <label className="block"><span className="label">{c("Sensitivity", "حساسیت")}</span><select className="field" value={selected.sensitivity} onChange={(e) => patchSelected({ sensitivity: e.target.value as CorrespondenceSensitivity })}>{(["standard", "confidential", "privileged_confidential", "without_prejudice"] as CorrespondenceSensitivity[]).map((value) => <option key={value} value={value}>{correspondenceSensitivityLabel(locale, value)}</option>)}</select></label>
            <label className="block"><span className="label">{c("Draft body", "متن پیش‌نویس")}</span><textarea className="field min-h-80 resize-y font-mono text-xs leading-6" dir="auto" value={selected.body} onChange={(e) => patchSelected({ body: e.target.value })} /></label>
            <div className="flex flex-wrap gap-2"><button className="secondary-button" disabled={busy} onClick={saveDraft}>{c("Save draft", "ذخیره پیش‌نویس")}</button><button className="primary-button" disabled={busy} onClick={() => transition("submit")}>{selected.review_history.length > 0 ? c("Submit revised state for re-review", "ارسال وضعیت اصلاح‌شده برای بازبینی مجدد") : c("Submit for manager review", "ارسال برای بازبینی مدیر")}</button></div>
          </div> : <div className="mt-5 whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm leading-7 text-slate-700" dir="auto">{selected.body}</div>}

          {selected.status === "under_review" && canReview ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm font-semibold text-amber-950">{selected.review_history.length > 0 ? c("Manager re-review decision", "تصمیم بازبینی مجدد مدیر") : c("Manager decision", "تصمیم مدیر")}</p>
            {selected.review_history.length > 0 ? <p className="mt-1 text-xs leading-5 text-amber-800">{c("A prior review remains in the immutable lineage. This decision will append a new review bound to the current state.", "بازبینی قبلی در زنجیره تغییرناپذیر باقی می‌ماند. این تصمیم یک بازبینی جدید متصل به وضعیت فعلی اضافه می‌کند.")}</p> : null}
            <textarea className="field mt-3 min-h-24" dir="auto" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder={c("Record the factual, recipient and sensitivity review.", "بازبینی واقعیت‌ها، گیرنده و حساسیت را ثبت کنید.")} />
            <div className="mt-3 flex gap-2"><button className="primary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("approve")}>{c("Approve wording", "تأیید متن")}</button><button className="secondary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("reject")}>{c("Reject to draft", "بازگرداندن به پیش‌نویس")}</button></div>
          </div> : null}

          {requestContextNeedsReview ? <div className="mt-5 rounded-xl border border-orange-200 bg-orange-50 p-4">
            <p className="text-sm font-semibold text-orange-950">{c("Document-request context changed", "زمینه درخواست سند تغییر کرده است")}</p>
            <p className="mt-1 text-xs leading-5 text-orange-800">{c("The wording itself may be unchanged, but the linked request/requirement context no longer matches the historical approval. Return the unchanged wording to human review before dispatch.", "ممکن است خود متن تغییر نکرده باشد، اما زمینه درخواست/الزامات متصل دیگر با تأیید تاریخی منطبق نیست. پیش از ارسال، همین متن بدون تغییر را دوباره برای بازبینی انسانی بفرستید.")}</p>
            <button className="secondary-button mt-3" disabled={busy} onClick={resubmitRequestContext}>{c("Re-review unchanged wording against current request context", "بازبینی مجدد متن بدون تغییر نسبت به زمینه فعلی درخواست")}</button>
          </div> : null}

          {selected.status === "approved" && !requestContextNeedsReview ? <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><p className="text-sm font-semibold text-violet-950">{c("Approved wording — choose the next human action", "متن تأیید شده — اقدام بعدی انسانی را انتخاب کنید")}</p><p className="mt-1 text-xs leading-5 text-violet-700">{c("If wording needs to change before dispatch, reopen it for revision. If it was actually sent outside the platform, record that external dispatch below.", "اگر متن پیش از ارسال باید تغییر کند، آن را برای اصلاح باز کنید. اگر واقعاً خارج از پلتفرم ارسال شده، ثبت ارسال خارجی را در پایین انجام دهید.")}</p></div>
              <button className="secondary-button" disabled={busy || selected.status !== "approved"} onClick={reopenForRevision}>{c("Revise before dispatch", "اصلاح پیش از ارسال")}</button>
            </div>
            <div className="mt-4 border-t border-violet-200 pt-4">
              <p className="text-sm font-semibold text-violet-950">{c("Record external dispatch", "ثبت ارسال خارجی")}</p>
              <p className="mt-1 text-xs leading-5 text-violet-700">{c("Complete this only after the approved wording has actually been sent outside the platform. Dispatch is bound to this exact approved review state.", "این بخش را فقط پس از آن تکمیل کنید که متن تأییدشده واقعاً خارج از پلتفرم ارسال شده باشد. ثبت ارسال به همین وضعیت بازبینی تأییدشده قفل است.")}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2"><label><span className="label">{c("Channel", "کانال")}</span><select className="field" value={dispatchChannel} onChange={(e) => setDispatchChannel(e.target.value as CorrespondenceChannel)}>{(["email", "letter", "portal", "phone", "meeting", "other"] as CorrespondenceChannel[]).map((value) => <option key={value} value={value}>{correspondenceChannelLabel(locale, value)}</option>)}</select></label><label><span className="label">{c("External reference", "مرجع خارجی")}</span><input className="field" dir="ltr" value={dispatchReference} onChange={(e) => setDispatchReference(e.target.value)} placeholder={c("Optional sent-mail or letter reference", "مرجع اختیاری ایمیل یا نامه ارسالی")} /></label></div>
              <label className="mt-3 flex items-start gap-2 text-sm text-violet-950"><input type="checkbox" className="mt-1" checked={confirmSent} onChange={(e) => setConfirmSent(e.target.checked)} /><span>{c("I confirm this exact approved correspondence was sent outside the platform.", "تأیید می‌کنم همین مکاتبه تأییدشده خارج از پلتفرم ارسال شده است.")}</span></label>
              <button className="primary-button mt-3" disabled={busy || !confirmSent || !selected.latest_review || selected.review_state !== "current"} onClick={markSent}>{c("Mark Sent Externally", "ثبت به‌عنوان ارسال‌شده خارج از پلتفرم")}</button>
            </div>
          </div> : null}

          {selected.status === "sent_externally" ? <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            <p>{c("Dispatch recorded via", "ارسال ثبت‌شده از طریق")} {selected.channel ? correspondenceChannelLabel(locale, selected.channel) : c("external channel", "کانال خارجی")}{selected.external_reference ? <span dir="ltr"> · {selected.external_reference}</span> : null}. {c("The platform did not send this message.", "پلتفرم این پیام را ارسال نکرده است.")}</p>
            {selected.sent_review_hash ? <p className="mt-2 text-xs" dir="ltr">sent review hash: {selected.sent_review_hash}</p> : null}
          </div> : null}

          {selected.review_history.length > 0 ? <section className="mt-6 border-t border-slate-200 pt-5" data-testid="correspondence-review-lineage">
            <div><h3 className="text-sm font-semibold text-slate-950">{c("Append-only review lineage", "زنجیره تغییرناپذیر بازبینی")}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{c("Historical decisions remain visible after revision. A later approval does not rewrite an earlier review.", "تصمیم‌های تاریخی پس از اصلاح همچنان قابل مشاهده‌اند. تأیید بعدی، بازبینی قبلی را بازنویسی نمی‌کند.")}</p></div>
            <div className="mt-3 space-y-3">{selected.review_history.map((review, index) => {
              const isLatest = index === selected.review_history.length - 1;
              const governsCurrent = review.correspondence_state_fingerprint === selected.state_fingerprint && review.state_version === selected.state_version && selected.review_state === "current";
              return <article key={review.id} className={`rounded-xl border p-4 ${isLatest ? "border-slate-300 bg-white" : "border-slate-200 bg-slate-50"}`}>
                <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-slate-900">{c("Review", "بازبینی")} #{review.review_number} · {correspondenceReviewActionLabel(locale, review.action)}</p><div className="flex gap-2">{isLatest ? <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-700">{c("Latest", "آخرین")}</span> : <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-500">{c("Historical", "تاریخی")}</span>}{governsCurrent ? <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-semibold text-emerald-700">{c("Current state", "وضعیت فعلی")}</span> : null}</div></div>
                <p className="mt-2 text-sm text-slate-700" dir="auto">{review.note}</p>
                <div className="mt-3 grid gap-1 text-[11px] text-slate-500 sm:grid-cols-2">
                  <p dir="ltr">reviewed: {formatDate(review.reviewed_at, locale)}</p>
                  <p dir="ltr">state v{review.state_version} · {review.correspondence_state_fingerprint.slice(0, 16)}…</p>
                  <p dir="ltr">review hash: {review.review_hash}</p>
                  {review.content_hash ? <p dir="ltr">content hash: {review.content_hash}</p> : null}
                  {review.request_context_fingerprint ? <p className="sm:col-span-2" dir="ltr">request context: {review.request_context_fingerprint}</p> : null}
                  {review.previous_review_hash ? <p className="sm:col-span-2" dir="ltr">previous review hash: {review.previous_review_hash}</p> : null}
                </div>
              </article>;
            })}</div>
          </section> : null}
        </>}
      </section>
    </div>
  </div>;
}
