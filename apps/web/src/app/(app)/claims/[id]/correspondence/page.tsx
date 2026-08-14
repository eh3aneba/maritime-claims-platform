"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

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
import type {
  Claim,
  ClaimCorrespondence,
  CorrespondenceChannel,
  CorrespondenceDirection,
  CorrespondenceKind,
  CorrespondenceSensitivity,
  CurrentUser,
} from "@/lib/types";

const sensitivityLabels: Record<CorrespondenceSensitivity, string> = {
  standard: "Standard",
  confidential: "Confidential",
  privileged_confidential: "Privileged & Confidential",
  without_prejudice: "Without Prejudice",
};

const statusTone: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  rejected: "bg-red-50 text-red-700",
  under_review: "bg-amber-50 text-amber-800",
  approved: "bg-violet-50 text-violet-700",
  sent_externally: "bg-emerald-50 text-emerald-700",
  received_external: "bg-cyan-50 text-cyan-700",
  filed_internal: "bg-blue-50 text-blue-700",
};

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
      setError(e instanceof ApiError ? e.detail : "Correspondence Centre could not be loaded.");
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
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Correspondence could not be created."); }
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
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Draft could not be saved."); }
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
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Correspondence status could not be updated."); }
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
    } catch (e) { setError(e instanceof ApiError ? e.detail : "External dispatch could not be recorded."); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading correspondence…</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || "Claim unavailable."}</div>;

  return <div>
    <Link href={"/claims/" + id} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to {claim.vessel.name}</Link>
    <div className="mt-5"><p className="eyebrow">{claim.claim_reference}</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Correspondence Centre</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">Draft, review and file claim communications with an audit trail. This centre does not send email or connect to a mailbox; “Sent Externally” only records a dispatch completed outside the platform.</p></div>

    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

    <section className="panel mt-6 p-6">
      <div><h2 className="section-title">Create correspondence</h2><p className="section-subtitle">Outbound items begin as editable drafts. Inbound and internal items are filed immediately as manual records.</p></div>
      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <label><span className="label">Direction</span><select className="field" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as CorrespondenceDirection })}><option value="outbound">Outbound draft</option><option value="inbound">Inbound record</option><option value="internal">Internal note</option></select></label>
        <label><span className="label">Type</span><select className="field" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as CorrespondenceKind })}><option value="general">General</option><option value="follow_up">Follow-up</option><option value="status_update">Status update</option><option value="reservation_of_rights">Reservation of rights</option><option value="settlement">Settlement</option></select></label>
        <label><span className="label">Sensitivity</span><select className="field" value={form.sensitivity} onChange={(e) => setForm({ ...form, sensitivity: e.target.value as CorrespondenceSensitivity })}>{Object.entries(sensitivityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {form.direction === "inbound" ? <label><span className="label">Sender</span><input className="field" value={form.sender_label} onChange={(e) => setForm({ ...form, sender_label: e.target.value })} placeholder="e.g. Average Adjuster" /></label> : null}
        {form.direction === "outbound" ? <label><span className="label">Recipient</span><input className="field" value={form.recipient_label} onChange={(e) => setForm({ ...form, recipient_label: e.target.value })} /></label> : null}
        <label><span className="label">Subject</span><input className="field" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder={claim.claim_reference + " – Status update"} /></label>
      </div>
      <label className="mt-4 block"><span className="label">Body</span><textarea className="field min-h-48 resize-y" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></label>
      <button className="primary-button mt-4" disabled={busy || form.subject.trim().length < 3 || form.body.trim().length < 3} onClick={createItem}>{busy ? "Working…" : form.direction === "outbound" ? "Create draft" : "File record"}</button>
    </section>

    <div className="mt-6 grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="panel p-4"><h2 className="px-2 text-sm font-semibold text-slate-950">Claim correspondence</h2><p className="px-2 text-xs text-slate-500">{items.length} record(s)</p><div className="mt-3 space-y-2">{items.map((item) => <button key={item.id} onClick={() => setSelectedId(item.id)} className={"w-full rounded-xl border p-3 text-left " + (item.id === selectedId ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white")}><div className="flex items-start justify-between gap-2"><p className="line-clamp-2 text-sm font-semibold text-slate-900">{item.subject}</p><span className={"shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold " + (statusTone[item.status] ?? "bg-slate-100 text-slate-700")}>{item.status.replaceAll("_", " ")}</span></div><p className="mt-2 text-xs text-slate-500">{item.direction} · {sensitivityLabels[item.sensitivity]}</p><p className="mt-1 text-[11px] text-slate-400">{formatDate(item.created_at)}</p></button>)}{!items.length ? <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">No correspondence recorded.</div> : null}</div></aside>

      <section className="panel p-6">
        {!selected ? <div className="py-20 text-center text-sm text-slate-500">Select a correspondence record.</div> : <>
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">{selected.direction} · {selected.kind.replaceAll("_", " ")}</p><h2 className="mt-1 text-xl font-semibold text-slate-950">{selected.subject}</h2></div><div className="flex flex-wrap gap-2"><span className={"rounded-full px-3 py-1.5 text-xs font-semibold " + (statusTone[selected.status] ?? "bg-slate-100 text-slate-700")}>{selected.status.replaceAll("_", " ")}</span><span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">{sensitivityLabels[selected.sensitivity]}</span></div></div>

          {["draft", "rejected"].includes(selected.status) ? <div className="mt-5 space-y-4"><label className="block"><span className="label">Recipient</span><input className="field" value={selected.recipient_label ?? ""} onChange={(e) => patchSelected({ recipient_label: e.target.value })} /></label><label className="block"><span className="label">Subject</span><input className="field" value={selected.subject} onChange={(e) => patchSelected({ subject: e.target.value })} /></label><label className="block"><span className="label">Sensitivity</span><select className="field" value={selected.sensitivity} onChange={(e) => patchSelected({ sensitivity: e.target.value as CorrespondenceSensitivity })}>{Object.entries(sensitivityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="block"><span className="label">Draft body</span><textarea className="field min-h-80 resize-y font-mono text-xs leading-6" value={selected.body} onChange={(e) => patchSelected({ body: e.target.value })} /></label><div className="flex flex-wrap gap-2"><button className="secondary-button" disabled={busy} onClick={saveDraft}>Save draft</button><button className="primary-button" disabled={busy} onClick={() => transition("submit")}>Submit for manager review</button></div></div> : <div className="mt-5 whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm leading-7 text-slate-700">{selected.body}</div>}

          {selected.review_note ? <div className="mt-4 rounded-xl border border-slate-200 p-4"><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">Review note</p><p className="mt-2 text-sm text-slate-700">{selected.review_note}</p></div> : null}

          {selected.status === "under_review" && canReview ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="text-sm font-semibold text-amber-950">Manager decision</p><textarea className="field mt-3 min-h-24" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Record the factual, recipient and sensitivity review." /><div className="mt-3 flex gap-2"><button className="primary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("approve")}>Approve wording</button><button className="secondary-button" disabled={busy || reviewNote.trim().length < 3} onClick={() => transition("reject")}>Reject to draft</button></div></div> : null}

          {selected.status === "approved" ? <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4"><p className="text-sm font-semibold text-violet-950">Record external dispatch</p><p className="mt-1 text-xs leading-5 text-violet-700">Complete this only after the approved wording has actually been sent outside the platform.</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><label><span className="label">Channel</span><select className="field" value={dispatchChannel} onChange={(e) => setDispatchChannel(e.target.value as CorrespondenceChannel)}><option value="email">Email</option><option value="letter">Letter</option><option value="portal">Portal</option><option value="phone">Phone</option><option value="meeting">Meeting</option><option value="other">Other</option></select></label><label><span className="label">External reference</span><input className="field" value={dispatchReference} onChange={(e) => setDispatchReference(e.target.value)} placeholder="Optional sent-mail or letter reference" /></label></div><label className="mt-3 flex items-start gap-2 text-sm text-violet-950"><input type="checkbox" className="mt-1" checked={confirmSent} onChange={(e) => setConfirmSent(e.target.checked)} /><span>I confirm this exact approved correspondence was sent outside the platform.</span></label><button className="primary-button mt-3" disabled={busy || !confirmSent} onClick={markSent}>Mark Sent Externally</button></div> : null}

          {selected.status === "sent_externally" ? <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">Dispatch recorded via {selected.channel ?? "external channel"}{selected.external_reference ? " · " + selected.external_reference : ""}. The platform did not send this message.</div> : null}
        </>}
      </section>
    </div>
  </div>;
}
