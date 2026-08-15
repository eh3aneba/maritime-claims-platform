"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError, createEmailIngestionConnection, expireDueIngestedEmail, getClaim,
  getCurrentUser, getEmailIngestionInbox, reviewIngestedEmail,
  transitionEmailIngestionConnection,
} from "@/lib/api";
import type { Claim, CurrentUser, EmailIngestionInbox } from "@/lib/types";

const tone: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700", linked: "bg-emerald-50 text-emerald-700",
  pending_review: "bg-amber-50 text-amber-800", suspended: "bg-amber-50 text-amber-800",
  revoked: "bg-red-50 text-red-700", rejected: "bg-red-50 text-red-700",
  expired: "bg-slate-100 text-slate-600",
};

export default function EmailIntakePage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null); const [user, setUser] = useState<CurrentUser | null>(null);
  const [inbox, setInbox] = useState<EmailIngestionInbox>({ connections: [], messages: [] });
  const [mailbox, setMailbox] = useState(""); const [retention, setRetention] = useState("30");
  const [consentBasis, setConsentBasis] = useState("Mailbox owner and organization approved claim-email intake.");
  const [oneTimeToken, setOneTimeToken] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const canManage = user?.role === "admin" || user?.role === "claims_manager";

  async function load() {
    try {
      const [c, u, i] = await Promise.all([getClaim(id), getCurrentUser(), getEmailIngestionInbox()]);
      setClaim(c); setUser(u); setInbox(i); setError("");
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Email Intake could not be loaded."); }
  }
  useEffect(() => { load(); }, [id]);
  async function run(task: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await task(); await load(); } catch (e) { setError(e instanceof ApiError ? e.detail : "Controlled email action failed."); }
    finally { setBusy(false); }
  }
  async function createConnection() {
    if (!mailbox) return setError("Enter the consented mailbox address.");
    setBusy(true); setError("");
    try {
      const created = await createEmailIngestionConnection({
        provider_label: "Normalized Webhook", mailbox_address: mailbox, consent_confirmed: true,
        consent_basis: consentBasis, retention_days: Number(retention),
      });
      setOneTimeToken(created.ingestion_token || ""); await load();
    } catch (e) { setError(e instanceof ApiError ? e.detail : "Connection could not be created."); }
    finally { setBusy(false); }
  }
  function note(label: string) { return window.prompt(label)?.trim() || ""; }
  if (!claim) return <div className="panel p-6 text-sm text-slate-600">{error || "Loading Email Intake…"}</div>;
  return <div>
    <Link href={"/claims/" + id + "/correspondence"} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to Correspondence Centre</Link>
    <p className="eyebrow mt-5">{claim.claim_reference} · consent-gated intake</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Controlled Email Intake</h1>
    <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">Inbound normalized email is staged for human review. Claim references are suggestions only. This workspace does not read an entire mailbox, send email, store provider OAuth tokens or admit attachment bytes as evidence.</p>
    <Link href={`/claims/${id}/email-adapters`} className="secondary-button mt-4">Open provider adapter operations</Link>
    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}
    {oneTimeToken ? <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-5"><p className="font-semibold text-amber-950">Copy the one-time ingestion token now</p><p className="mt-2 break-all font-mono text-xs text-amber-900">{oneTimeToken}</p><p className="mt-2 text-xs text-amber-800">Only its SHA-256 hash is stored; it cannot be displayed again.</p></div> : null}
    <div className="mt-6 grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="space-y-5">
        {canManage ? <section className="panel p-5"><h2 className="section-title">Consent &amp; retention</h2><label className="mt-4 block"><span className="label">Mailbox address</span><input className="field" type="email" value={mailbox} onChange={(e) => setMailbox(e.target.value)} /></label><label className="mt-3 block"><span className="label">Retention days (1–365)</span><input className="field" type="number" min="1" max="365" value={retention} onChange={(e) => setRetention(e.target.value)} /></label><label className="mt-3 block"><span className="label">Recorded consent basis</span><textarea className="field min-h-24" value={consentBasis} onChange={(e) => setConsentBasis(e.target.value)} /></label><button className="primary-button mt-3" disabled={busy} onClick={createConnection}>Create intake connection</button><button className="secondary-button mt-2" disabled={busy} onClick={() => run(expireDueIngestedEmail)}>Apply due retention expiry</button></section> : null}
        <section className="panel p-5"><h2 className="section-title">Connections</h2><div className="mt-3 space-y-3">{inbox.connections.map((x) => <div key={x.id} className="rounded-xl border border-slate-200 p-3"><div className="flex items-center justify-between gap-2"><p className="text-sm font-semibold">{x.mailbox_address}</p><span className={"rounded-full px-2 py-1 text-[10px] font-semibold " + (tone[x.status] || "bg-slate-100")}>{x.status}</span></div><p className="mt-1 text-xs text-slate-500">{x.provider_label} · {x.retention_days} day retention</p>{canManage && x.status !== "revoked" ? <div className="mt-2 flex gap-2"><button className="secondary-button px-2 py-1 text-xs" onClick={() => { const n = note("Lifecycle reason"); if (n) run(() => transitionEmailIngestionConnection(x.id, x.status === "active" ? "suspend" : "reactivate", n)); }}>{x.status === "active" ? "Suspend" : "Reactivate"}</button><button className="secondary-button px-2 py-1 text-xs" onClick={() => { const n = note("Consent withdrawal/revocation reason"); if (n) run(() => transitionEmailIngestionConnection(x.id, "revoke", n)); }}>Revoke</button></div> : null}</div>)}{!inbox.connections.length ? <p className="text-sm text-slate-500">No consented connection.</p> : null}</div></section>
      </aside>
      <main className="panel p-6"><h2 className="section-title">Human review queue</h2><p className="section-subtitle">Linking creates an inbound Correspondence record. Attachment manifests stay blocked pending quarantine admission.</p><div className="mt-4 space-y-4">{inbox.messages.map((x) => <article key={x.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-slate-900">{x.subject}</p><p className="mt-1 text-xs text-slate-500">From {x.sender} · received {new Date(x.received_at).toLocaleString()}</p></div><span className={"rounded-full px-3 py-1 text-xs font-semibold " + (tone[x.status] || "bg-slate-100")}>{x.status.replaceAll("_", " ")}</span></div><p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{x.body_text}</p>{x.suggested_claim_id ? <p className="mt-3 text-xs font-semibold text-amber-800">Deterministic suggestion: {x.suggested_claim_id === id ? claim.claim_reference : "another tenant claim"} — human confirmation required</p> : null}{x.attachments.length ? <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{x.attachments.map((a) => <p key={a.id}>{a.filename} · {a.admission_status.replaceAll("_", " ")}</p>)}</div> : null}{x.status === "pending_review" ? <div className="mt-3 flex flex-wrap gap-2"><button className="primary-button" disabled={busy} onClick={() => { const n = note("Why does this email belong to this claim?"); if (n) run(() => reviewIngestedEmail(x.id, { action: "link", claim_id: id, confirm_link: true, sensitivity: "standard", note: n })); }}>Link to {claim.claim_reference}</button><button className="secondary-button" disabled={busy} onClick={() => { const n = note("Rejection reason"); if (n) run(() => reviewIngestedEmail(x.id, { action: "reject", note: n })); }}>Reject intake</button></div> : null}<p className="mt-3 text-[10px] text-slate-400">Retention due {new Date(x.retain_until).toLocaleDateString()} · hash {x.content_hash.slice(0, 12)}…</p></article>)}{!inbox.messages.length ? <p className="py-12 text-center text-sm text-slate-500">No staged inbound email.</p> : null}</div></main>
    </div>
  </div>;
}
