"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import {
  ApiError,
  createClaimCorrespondence,
  getClaim,
  getCurrentUser,
  listClaimCorrespondence,
  markClaimCorrespondenceSent,
  reviewClaimCorrespondence,
  submitClaimCorrespondence,
  updateClaimCorrespondence,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import {
  correspondenceChannelLabel,
  correspondenceDirectionLabel,
  correspondenceDirectionOptionLabel,
  correspondenceKindLabel,
  correspondenceKindOptionLabel,
  correspondenceSensitivityLabel,
  correspondenceStatusLabel,
  correspondenceT,
} from "@/lib/i18n-correspondence-export";
import type {
  Claim,
  ClaimCorrespondence,
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

// This is correspondence content, not UI copy. It intentionally remains English
// when the operator changes locale and is never machine-translated by Phase 12K.
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
  const [items, setItems] = useState<ClaimCorrespondence[]>([]);
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
      const [claimData, userData, correspondence] = await Promise.all([getClaim(id), getCurrentUser(), listClaimCorrespondence(id)]);
      setClaim(claimData); setUser(userData); setItems(correspondence.items);
      setSelectedId(preferId ?? selectedId ?? correspondence.items[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : c("Correspondence Centre could not be loaded.", "مرکز مکاتبات قابل بارگذاری نیست."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [id]);

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
      setForm(initialForm); await load(item.id);
    } catch (e) { setError(e instanceof ApiError ? e.detail : c("Correspondence could not be created.", "مکاتبه ایجاد نشد.")); }
    finally { setBusy(false); }
  }

  async function saveDraft() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await updateClaimCorrespondence(id, selected.id, {
        sensitivity: selected.sensitivity,
        recipient_label: selected.recipient_label,
        subject: selected.subject,
        body: selected.body,
      });
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) { setError(e instanceof ApiError ? e.detail : c("Draft could not be saved.", "پیش‌نویس ذخیره نشد.")); }
    finally { setBusy(false); }
  }

  function patchSelected(patch: Partial<ClaimCorrespondence>) {
    if (!selected) return;
    setItems((current) => current.map((item) => item.id === selected.id ? { ...item, ...patch } : item));
  }

  async function transition(action: "submit" | "approve" | "reject") {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = action === "submit"
        ? await submitClaimCorrespondence(id, selected.id)
        : await reviewClaimCorrespondence(id, selected.id, action, reviewNote.trim());
      setReviewNote(""); setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) { setError(e instanceof ApiError ? e.detail : c("Correspondence status could not be updated.", "وضعیت مکاتبه به‌روزرسانی نشد.")); }
    finally { setBusy(false); }
  }

  async function markSent() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const updated = await markClaimCorrespondenceSent(id, selected.id, {
        confirm_sent: confirmSent,
        channel: dispatchChannel,
        external_reference: dispatchReference.trim() || null,
      });
      setConfirmSent(false); setDispatchReference("");
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (e) { setError(e instanceof ApiError ? e.detail : c("External dispatch could not be recorded.", "ثبت ارسال خارجی انجام نشد.")); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">{c("Loading correspondence…", "در حال بارگذاری مکاتبات…")}</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || c("Claim unavailable.", "پرونده در دسترس نیست.")}</div>;

  return <div>
    <Link href={"/claims/" + id} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{locale === "fa" ? "→" : "←"} {c(`Back to ${claim.vessel.name}`, `بازگشت به ${claim.vessel.name}`)}</Link>
    <div className="mt-5"><p className="eyebrow" dir="ltr">{claim.claim_reference}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{c("Correspondence Centre", "مرکز مکاتبات")}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{c("Draft, review and file claim communications with an audit trail. This centre does not send email or connect to a mailbox; “Sent Externally” only records a dispatch completed outside the platform.", "مکاتبات پرونده را با ردپای حسابرسی پیش‌نویس، بازبینی و ثبت کنید. این مرکز ایمیل ارسال نمی‌کند و به صندوق پستی متصل نیست؛ «ثبت ارسال خارجی» فقط ارسالی را ثبت می‌کند که خارج از پلتفرم انجام شده است.")}</p></div>

    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

    <section className="panel mt-6 p-6">
      <div><h2 className="section-title">{c("Create correspondence", "ایجاد مکاتبه")}</h2><p className="section-subtitle">{c("Outbound items begin as editable drafts. Inbound and internal items are filed immediately as manual records.", "موارد خروجی به‌صورت پیش‌نویس قابل ویرایش آغاز می‌شوند. موارد ورودی و داخلی بلافاصله به‌عنوان رکورد دستی ثبت می‌شوند.")}</p></div>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <label><span className="label">{c("Direction", "جهت")}</span><select className="field" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as CorrespondenceDirection })}><option value="outbound">{correspondenceDirectionOptionLabel(locale, "outbound")}</option><option value="inbound">{correspondenceDirectionOptionLabel(locale, "inbound")}</option><option value="internal">{correspondenceDirectionOptionLabel(locale, "internal")}</option></select></label>
        <label><span className="label">{c("Type", "نوع")}</span><select className="field" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as CorrespondenceKind })}><option value="general">{correspondenceKindOptionLabel(locale, "general")}</option><option value="follow_up">{correspondenceKindOptionLabel(locale, "follow_up")}</option><option value="status_update">{correspondenceKindOptionLabel(locale, "status_update")}</option><option value="reservation_of_rights">{correspondenceKindOptionLabel(locale, "reservation_of_rights")}</option><option value="settlement">{correspondenceKindOptionLabel(locale, "settlement")}</option></select></label>
        <label><span className="label">{c("Sensitivity", "حساسیت")}</span><select className="field" value={form.sensitivity} onChange={(e) => setForm({ ...form, sensitivity: e.target.value as CorrespondenceSensitivity })}>{(["standard", "confidential", "privileged_confidential", "without_prejudice"] as CorrespondenceSensitivity[]).map((value) => <option key={value} value={value}>{correspondenceSensitivityLabel(locale, value)}</option>)}</select></label>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {form.direction === "inbound" ? <label><span className="label">{c("Sender", "فرستنده")}</span><input className="field" dir="auto" value={form.sender_label} onChange={(e) => setForm({ ...form, sender_label: e.target.value })} placeholder={c("e.g. Average Adjuster", "مثلاً Average Adjuster")} /></label> : null}
        {form.direction === "outbound" ? <label><span className="label">{c("Recipient", "گیرنده")}</span><input className="field" dir="auto" value={form.recipient_label} onChange={(e) => setForm({ ...form, recipient_label: e.target.value })} /></label> : null}
        <label><span className="label">{c("Subject", "موضوع")}</span><input className="field" dir="auto" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder={claim.claim_reference + " – Status update"} /></label>
      </div>
      <label className="mt-4 block"><span className="label">{c("Body", "متن مکاتبه")}</span><textarea className="field min-h-48 resize-y" dir="auto" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
      <button className="primary-button mt-4" disabled={busy || form.subject.trim().length < 3 || form.body.trim().length < 3} onClick={createItem}>{busy ? c("Working…", "در حال انجام…") : form.direction === "outbound" ? c("Create draft", "ایجاد پیش‌نویس") : c("File record", "ثبت رکورد")}</button>
    </section>

    <div className="mt-6 grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="panel p-4"><h2 className="px-2 text-sm font-semibold text-slate-950">{c("Claim correspondence", "مکاتبات پرونده")}</h2><p className="px-2 text-xs text-slate-500">{locale === "fa" ? `${items.length} رکورد` : `${items.length} record(s)`}</p><div className="mt-3 space-y-2">{items.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full rounded-xl border p-3 ${locale === "fa" ? "text-right" : "text-left"} ${item.id === selectedId ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white"}`}><div className="flex items-start justify-between gap-2"><p className="line-clamp-2 text-sm font-semibold text-slate-900" dir="auto">{item.subject}</p><span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${statusTone[item.status] ?? "bg-slate-100 text-slate-700"}`}>{correspondenceStatusLabel(locale, item.status)}</span></div><p className="mt-2 text-xs text-slate-500">{correspondenceDirectionLabel(locale, item.direction)} · {correspondenceSensitivityLabel(locale, item.sensitivity)}</p><p className="mt-1 text-[11px] text-slate-400" dir="ltr">{formatDate(item.created_at, locale)}</p></button>)}{!items.length ? <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">{c("No correspondence recorded.", "مکاتبه‌ای ثبت نشده است.")}</div> : null}</div></aside>

      <section className="panel p-6">
        {!selected ? <div className="py-20 text-center text-sm text-slate-500">{c("Select a correspondence record.", "یک رکورد مکاتبه را انتخاب کنید.")}</div> : <>
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">{correspondenceDirectionLabel(locale, selected.direction)} · {correspondenceKindLabel(locale, selected.kind)}</p><h2 className="mt-1 text-xl font-semibold text-slate-950" dir="auto">{selected.subject}</h2></div><div className="flex flex-wrap gap-2"><span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${statusTone[selected.status] ?? "bg-slate-100 text-slate-700"}`}>{correspondenceStatusLabel(locale, selected.status)}</span><span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">{correspondenceSensitivityLabel(locale, selected.sensitivity)}</span></div></div>

          {["draft", "rejected"].includes(selected.status) ? <div className="mt-5 space-y-4"><label className="block"><span className="label">{c("Recipient", "گیرنده")}</span><input className="field" dir="auto" value={selected.recipient_label ?? ""} onChange={(e) => patchSelected({ recipient_label: e.target.value })} /></label><label className="block"><span className="label">{c("Subject", "موضوع")}</span><input className="field" dir="auto" value={selected.subject} onChange={(e) => patchSelected({ subject: e.target.value })} /></label><label className="block"><span className="label">{c("Sensitivity", "حساسیت")}</span><select className="field" value={selected.sensitivity} onChange={(e) => patchSelected({ sensitivity: e.target.value as CorrespondenceSensitivity })}>{(["standard", "confidential", "privileged_confidential", "without_prejudice"] as CorrespondenceSensitivity[]).map((value) => <option key={value} value={value}>{correspondenceSensitivityLabel(locale, value)}</option>)}</select></label><label className="block"><span className="label">{c("Draft body", "متن پیش‌نویس")}</span><textarea className="field min-h-80 resize-y font-mono text-xs leading-6" dir="auto" value={selected.body} onChange={(e) => patchSelected({ body: e.target.value })} /></label><div className="flex flex-wrap gap-2"><button className="secondary-button" disabled={busy} onClick={saveDraft}>{c("Save draft", "ذخیره پیش‌نویس")}</button><button className="primary-button" disabled={busy} onClick={() => transition("submit")}>{c("Submit for manager review", "ارسال برای بازبینی مدیر")}</button></div></div> : <div className="mt-5 whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm leading-7 text-slate-700" dir="auto">{selected.body}</div>}

          {selected.review_note ? <div className="mt-4 rounded-xl border border-slate-200 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">{c("Review note", "یادداشت بازبینی")}</p><p className="mt-2 text-sm text-slate-700" dir="auto">{selected.review_note}</p></div> : null}

          {selected.status === "under_review" && canReview ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm font-semibold text-amber-950">{c("Manager decision", "تصمیم مدیر")}</p><textarea className="field mt-3 min-h-24" dir="auto" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder={c("Record the factual, recipient and sensitivity review.", "بازبینی واقعیت‌ها، گیرنده و حساسیت را ثبت کنید.")} /><div className="mt-3 flex gap-2"><button className="primary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("approve")}>{c("Approve wording", "تأیید متن")}</button><button className="secondary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("reject")}>{c("Reject to draft", "بازگرداندن به پیش‌نویس")}</button></div></div> : null}

          {selected.status === "approved" ? <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4"><p className="text-sm font-semibold text-violet-950">{c("Record external dispatch", "ثبت ارسال خارجی")}</p><p className="mt-1 text-xs leading-5 text-violet-700">{c("Complete this only after the approved wording has actually been sent outside the platform.", "این بخش را فقط پس از آن تکمیل کنید که متن تأییدشده واقعاً خارج از پلتفرم ارسال شده باشد.")}</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><label><span className="label">{c("Channel", "کانال")}</span><select className="field" value={dispatchChannel} onChange={(e) => setDispatchChannel(e.target.value as CorrespondenceChannel)}>{(["email", "letter", "portal", "phone", "meeting", "other"] as CorrespondenceChannel[]).map((value) => <option key={value} value={value}>{correspondenceChannelLabel(locale, value)}</option>)}</select></label><label><span className="label">{c("External reference", "مرجع خارجی")}</span><input className="field" dir="ltr" value={dispatchReference} onChange={(e) => setDispatchReference(e.target.value)} placeholder={c("Optional sent-mail or letter reference", "مرجع اختیاری ایمیل یا نامه ارسالی")} /></label></div><label className="mt-3 flex items-start gap-2 text-sm text-violet-950"><input type="checkbox" className="mt-1" checked={confirmSent} onChange={(e) => setConfirmSent(e.target.checked)} /><span>{c("I confirm this exact approved correspondence was sent outside the platform.", "تأیید می‌کنم همین مکاتبه تأییدشده خارج از پلتفرم ارسال شده است.")}</span></label><button className="primary-button mt-3" disabled={busy || !confirmSent} onClick={markSent}>{c("Mark Sent Externally", "ثبت به‌عنوان ارسال‌شده خارج از پلتفرم")}</button></div> : null}

          {selected.status === "sent_externally" ? <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{c("Dispatch recorded via", "ارسال ثبت‌شده از طریق")} {selected.channel ? correspondenceChannelLabel(locale, selected.channel) : c("external channel", "کانال خارجی")}{selected.external_reference ? <span dir="ltr"> · {selected.external_reference}</span> : null}. {c("The platform did not send this message.", "پلتفرم این پیام را ارسال نکرده است.")}</div> : null}
        </>}
      </section>
    </div>
  </div>;
}
