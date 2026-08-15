"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, createEmailProviderAdapter, getEmailAdapterOperations, getEmailIngestionInbox, recordEmailAdapterRun, runScheduledEmailRetention, transitionEmailProviderAdapter } from "@/lib/api";
import type { EmailAdapterOperations, EmailIngestionConnection } from "@/lib/types";

export default function EmailAdapterOperationsPage() {
  const { id } = useParams<{ id: string }>();
  const [connections, setConnections] = useState<EmailIngestionConnection[]>([]);
  const [ops, setOps] = useState<EmailAdapterOperations>({ adapters: [], runs: [], retention_runs: [] });
  const [connectionId, setConnectionId] = useState(""); const [folder, setFolder] = useState("Claims Intake");
  const [secretRef, setSecretRef] = useState("vault://mcri/email-provider");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function load() { try { const [i, o] = await Promise.all([getEmailIngestionInbox(), getEmailAdapterOperations()]); setConnections(i.connections); setConnectionId((v) => v || i.connections.find((x) => x.status === "active")?.id || ""); setOps(o); setError(""); } catch (e) { setError(e instanceof ApiError ? e.detail : "Adapter operations could not be loaded."); } }
  useEffect(() => { load(); }, []);
  async function run(task: () => Promise<unknown>) { setBusy(true); try { await task(); await load(); } catch (e) { setError(e instanceof ApiError ? e.detail : "Operation failed."); } finally { setBusy(false); } }
  return <div>
    <Link href={`/claims/${id}/email-intake`} className="text-sm font-semibold text-slate-500">← Back to Controlled Email Intake</Link>
    <p className="eyebrow mt-5">Sprint 9F · operational boundary</p><h1 className="mt-2 text-3xl font-semibold">Email Provider Adapter Operations</h1>
    <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">Adapters read only the allowlisted folder through deployment-managed credentials. The application stores a secret reference—not OAuth tokens—and cannot send, delete, archive or reply to email.</p>
    {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}
    <div className="mt-6 grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
      <aside className="panel p-5"><h2 className="section-title">Least-privilege adapter</h2>
        <label className="mt-4 block"><span className="label">Consented connection</span><select className="field" value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>{connections.map((x) => <option key={x.id} value={x.id}>{x.mailbox_address}</option>)}</select></label>
        <label className="mt-3 block"><span className="label">Allowlisted folder</span><input className="field" value={folder} onChange={(e) => setFolder(e.target.value)} /></label>
        <label className="mt-3 block"><span className="label">Deployment secret reference</span><input className="field" value={secretRef} onChange={(e) => setSecretRef(e.target.value)} /></label>
        <button className="primary-button mt-4" disabled={busy || !connectionId} onClick={() => run(() => createEmailProviderAdapter({ connection_id: connectionId, provider_kind: "provider_webhook", display_name: "Controlled provider worker", credential_reference: secretRef, allowed_folder: folder, permission_manifest: ["messages.read.allowed_folder", "attachments.metadata.read"], batch_limit: 50, retention_schedule_enabled: true }))}>Register adapter</button>
        <button className="secondary-button mt-2" disabled={busy} onClick={() => run(runScheduledEmailRetention)}>Run due retention</button>
      </aside>
      <main className="space-y-5"><section className="panel p-5"><h2 className="section-title">Adapters</h2><div className="mt-3 space-y-3">{ops.adapters.map((x) => <div key={x.id} className="rounded-xl border border-slate-200 p-4"><div className="flex justify-between gap-3"><div><p className="font-semibold">{x.display_name}</p><p className="mt-1 text-xs text-slate-500">{x.allowed_folder} · max {x.batch_limit} · {x.permission_manifest.join(", ")}</p><p className="mt-1 font-mono text-[10px] text-slate-400">{x.credential_reference}</p></div><span className="text-xs font-semibold">{x.status}</span></div>{x.status !== "revoked" ? <div className="mt-3 flex flex-wrap gap-2"><button className="secondary-button" onClick={() => run(() => recordEmailAdapterRun(x.id))}>Record bounded run</button><button className="secondary-button" onClick={() => { const note = window.prompt("Lifecycle reason")?.trim(); if (note) run(() => transitionEmailProviderAdapter(x.id, x.status === "active" ? "suspend" : "reactivate", note)); }}>{x.status === "active" ? "Suspend" : "Reactivate"}</button><button className="secondary-button" onClick={() => { const note = window.prompt("Revocation reason")?.trim(); if (note) run(() => transitionEmailProviderAdapter(x.id, "revoke", note)); }}>Revoke</button></div> : null}</div>)}{!ops.adapters.length ? <p className="text-sm text-slate-500">No adapter registered.</p> : null}</div></section>
        <section className="panel p-5"><h2 className="section-title">Observable run ledger</h2><div className="mt-3 space-y-2">{ops.runs.map((x) => <p key={x.id} className="rounded-lg bg-slate-50 p-3 text-xs">{x.trigger} · {x.status} · {x.messages_ingested}/{x.messages_seen} ingested · {new Date(x.started_at).toLocaleString()}</p>)}{!ops.runs.length ? <p className="text-sm text-slate-500">No run recorded.</p> : null}</div></section></main>
    </div>
  </div>;
}
