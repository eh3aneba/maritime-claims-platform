"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ClaimDocuments } from "@/components/claim-documents";
import { useLocale } from "@/components/locale-provider";
import { PriorityText, StatusBadge } from "@/components/status-badge";
import { ApiError, changeClaimReserve, changeClaimStatus, getClaim, getClaimFacts } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import { claimWorkspaceT, type ClaimWorkspaceKey } from "@/lib/i18n-claim-workspace";
import type { TranslationKey } from "@/lib/i18n";
import type { Claim, ClaimFact, ClaimPriority, ClaimStatus } from "@/lib/types";

const statusFlow: ClaimStatus[] = ["new","triage","awaiting_documents","investigation","technical_review","financial_review","coverage_review","negotiation","settlement","recovery","closed"];
const statusKeys: Record<ClaimStatus, TranslationKey> = {
  new: "status.new", triage: "status.triage", awaiting_documents: "status.awaiting_documents", investigation: "status.investigation",
  technical_review: "status.technical_review", financial_review: "status.financial_review", coverage_review: "status.coverage_review",
  negotiation: "status.negotiation", settlement: "status.settlement", recovery: "status.recovery", closed: "status.closed",
  on_hold: "status.on_hold", litigation: "status.litigation", rejected: "status.rejected", withdrawn: "status.withdrawn",
};
const priorityKeys: Record<ClaimPriority, TranslationKey> = {
  low: "priority.low", medium: "priority.medium", high: "priority.high", critical: "priority.critical",
};

type WorkspaceCard = { title: ClaimWorkspaceKey; help: ClaimWorkspaceKey; open: ClaimWorkspaceKey; href: (claimId: string) => string };
const localizedCards: WorkspaceCard[] = [
  { title: "overview.card.ai.title", help: "overview.card.ai.help", open: "overview.card.ai.open", href: (id) => `/ai-review?claim_id=${id}` },
  { title: "overview.card.assessment.title", help: "overview.card.assessment.help", open: "overview.card.assessment.open", href: (id) => `/claims/${id}/assessment` },
  { title: "overview.card.financial.title", help: "overview.card.financial.help", open: "overview.card.financial.open", href: (id) => `/claims/${id}/financial` },
  { title: "overview.card.technical.title", help: "overview.card.technical.help", open: "overview.card.technical.open", href: (id) => `/claims/${id}/technical` },
  { title: "overview.card.evidence.title", help: "overview.card.evidence.help", open: "overview.card.evidence.open", href: (id) => `/claims/${id}/evidence-matrix` },
  { title: "overview.card.chronology.title", help: "overview.card.chronology.help", open: "overview.card.chronology.open", href: (id) => `/claims/${id}/chronology` },
  { title: "overview.card.correspondence.title", help: "overview.card.correspondence.help", open: "overview.card.correspondence.open", href: (id) => `/claims/${id}/correspondence` },
  { title: "overview.card.claimPack.title", help: "overview.card.claimPack.help", open: "overview.card.claimPack.open", href: (id) => `/claims/${id}/claim-pack` },
  { title: "overview.card.policy.title", help: "overview.card.policy.help", open: "overview.card.policy.open", href: (id) => `/claims/${id}/policy-intelligence` },
  { title: "overview.card.adjustment.title", help: "overview.card.adjustment.help", open: "overview.card.adjustment.open", href: (id) => `/claims/${id}/adjustment` },
  { title: "overview.card.settlement.title", help: "overview.card.settlement.help", open: "overview.card.settlement.open", href: (id) => `/claims/${id}/settlement-payments` },
  { title: "overview.card.rules.title", help: "overview.card.rules.help", open: "overview.card.rules.open", href: (id) => `/claims/${id}/rules` },
];

const deferredModuleCards = [
  ["Controlled Email Intake", "Review consent-gated inbound email before any human-confirmed claim link; attachment manifests remain outside active evidence.", "Open controlled email intake", "email-intake"],
  ["Email Adapter Operations", "Operate least-privilege provider adapters with bounded runs, secret references and scheduled retention.", "Open email adapter operations", "email-adapters"],
  ["External Collaboration Portal", "Invite a named external participant into a short-lived, claim-scoped and explicitly published workspace.", "Open external collaboration portal", "external-portal"],
  ["Pilot Operations", "Review deployment gates, content-free monitoring, incidents, governance and a manifest-only pilot exit.", "Open pilot operations", "pilot-operations"],
] as const;

export default function ClaimOverviewPage() {
  const { id } = useParams<{ id: string }>();
  const { locale, t } = useLocale();
  const cw = (key: ClaimWorkspaceKey, values?: Record<string, string | number>) => claimWorkspaceT(locale, key, values);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [approvedFacts, setApprovedFacts] = useState<ClaimFact[]>([]);
  const [error, setError] = useState("");
  const [updating, setUpdating] = useState(false);
  const [reserve, setReserve] = useState("");
  const [reserveReason, setReserveReason] = useState("");

  useEffect(() => {
    Promise.all([getClaim(id), getClaimFacts(id)])
      .then(([c, facts]) => { setClaim(c); setReserve(c.current_reserve ?? ""); setApprovedFacts(facts.items); setError(""); })
      .catch((e) => setError(e instanceof ApiError ? e.detail : cw("overview.loadError")));
  }, [id]);

  async function advanceStatus() {
    if (!claim) return;
    const index = statusFlow.indexOf(claim.status);
    if (index < 0 || index >= statusFlow.length - 1) return;
    setUpdating(true); setError("");
    try {
      // Audit reason is intentionally locale-neutral and unchanged from the pre-localization workflow.
      setClaim(await changeClaimStatus(claim.id, statusFlow[index + 1], "Advanced from claim overview"));
    } catch (e) { setError(e instanceof ApiError ? e.detail : cw("overview.advanceError")); }
    finally { setUpdating(false); }
  }

  async function saveReserve() {
    if (!claim || !reserve || reserveReason.trim().length < 3) { setError(cw("overview.reserveValidation")); return; }
    setUpdating(true); setError("");
    try { const updated = await changeClaimReserve(claim.id, Number(reserve), reserveReason.trim()); setClaim(updated); setReserveReason(""); }
    catch (e) { setError(e instanceof ApiError ? e.detail : cw("overview.reserveError")); }
    finally { setUpdating(false); }
  }

  if (!claim && !error) return <div className="py-20 text-center text-sm text-slate-500">{cw("overview.loading")}</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error}</div>;

  const nextIndex = statusFlow.indexOf(claim.status) + 1;
  const nextStatus = nextIndex > 0 && nextIndex < statusFlow.length ? statusFlow[nextIndex] : null;
  const statusText = (status: ClaimStatus) => t(statusKeys[status]);
  const priorityText = (priority: ClaimPriority) => t(priorityKeys[priority]);

  return (
    <div>
      <Link href="/claims" className="text-sm font-semibold text-slate-500 hover:text-slate-800">{locale === "fa" ? "→" : "←"} {cw("backToClaims")}</Link>
      <div className="mt-5 flex flex-col justify-between gap-5 xl:flex-row xl:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-3"><p className="eyebrow" dir="ltr">{claim.claim_reference}</p><StatusBadge status={claim.status} /></div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">{claim.vessel.name}</h1>
          <p className="mt-2 text-sm text-slate-500"><span dir="ltr">H&amp;M</span> · {locale === "fa" ? "خسارت ماشین‌آلات" : "Machinery Damage"}{claim.vessel.imo_number ? <span dir="ltr"> · IMO {claim.vessel.imo_number}</span> : null}</p>
        </div>
        <div className="flex flex-wrap gap-3">{nextStatus ? <button disabled={updating} onClick={advanceStatus} className="secondary-button">{cw("overview.advanceTo", { status: statusText(nextStatus) })}</button> : null}<button className="primary-button" onClick={() => document.getElementById("claim-evidence")?.scrollIntoView({ behavior: "smooth" })}>{cw("overview.uploadDocument")}</button></div>
      </div>

      {error ? <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5"><p className="metric-label">{cw("overview.incidentDate")}</p><p className="metric-value text-xl" dir="ltr">{formatDate(claim.incident_date, locale)}</p></div>
        <div className="panel p-5"><p className="metric-label">{cw("overview.priority")}</p><div className="mt-3"><PriorityText priority={claim.priority} /></div><p className="mt-2 text-xs text-slate-400">{cw("overview.caseAttention", { priority: priorityText(claim.priority) })}</p></div>
        <div className="panel p-5"><p className="metric-label">{cw("overview.estimatedLoss")}</p><p className="metric-value" dir="ltr">{formatMoney(claim.estimated_loss, claim.currency, locale)}</p></div>
        <div className="panel p-5"><p className="metric-label">{cw("overview.currentReserve")}</p><p className="metric-value" dir="ltr">{formatMoney(claim.current_reserve, claim.currency, locale)}</p></div>
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <section className="panel p-6">
            <h2 className="section-title">{cw("overview.title")}</h2><p className="section-subtitle">{cw("overview.help")}</p>
            <dl className="mt-6 grid gap-x-10 gap-y-5 sm:grid-cols-2">
              <div><dt className="detail-label">{cw("overview.status")}</dt><dd className="detail-value">{statusText(claim.status)}</dd></div>
              <div><dt className="detail-label">{cw("overview.handler")}</dt><dd className="detail-value">{claim.handler?.full_name ?? t("common.unassigned")}</dd></div>
              <div><dt className="detail-label">{cw("overview.notificationDate")}</dt><dd className="detail-value" dir="ltr">{formatDate(claim.notification_date, locale)}</dd></div>
              <div><dt className="detail-label">{cw("overview.externalReference")}</dt><dd className="detail-value" dir="ltr">{claim.external_reference ?? "—"}</dd></div>
            </dl>
            <div className="mt-6 border-t border-slate-200 pt-5"><p className="detail-label">{cw("overview.incidentDescription")}</p><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{claim.incident_description}</p></div>
          </section>

          <section className="panel p-6">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><h2 className="section-title">{cw("overview.approvedFacts")}</h2><p className="section-subtitle">{cw("overview.approvedFactsHelp")}</p></div><Link href={`/ai-review?claim_id=${claim.id}`} className="secondary-button whitespace-nowrap">{cw("overview.reviewAiEvidence")}</Link></div>
            {approvedFacts.length ? <div className="mt-5 overflow-x-auto"><table className="data-table"><thead><tr><th>{cw("overview.field")}</th><th>{cw("overview.approvedValue")}</th><th>{cw("overview.version")}</th><th>{cw("overview.approved")}</th></tr></thead><tbody>{approvedFacts.map((fact) => <tr key={fact.id}><td><div className="font-medium text-slate-800" dir="ltr">{fact.field_path.replaceAll("_", " ")}</div></td><td><div className="max-w-xl break-words font-medium text-slate-800">{typeof fact.value === "object" ? JSON.stringify(fact.value) : String(fact.value ?? "—")}</div></td><td dir="ltr">v{fact.version}</td><td dir="ltr">{formatDate(fact.approved_at, locale)}</td></tr>)}</tbody></table></div> : <div className="mt-5 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center text-sm text-slate-500">{cw("overview.noApprovedFacts")}</div>}
          </section>

          <div id="claim-evidence"><ClaimDocuments claimId={claim.id} /></div>
        </div>

        <aside className="space-y-5">
          {localizedCards.map((card) => <section key={card.title} className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">{cw(card.title)}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{cw(card.help)}</p><Link href={card.href(claim.id)} className="secondary-button mt-4 w-full justify-center">{cw(card.open)}</Link></section>)}

          {deferredModuleCards.map(([title, help, open, route]) => <section key={route} className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">{title}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{help}</p><Link href={`/claims/${claim.id}/${route}`} className="secondary-button mt-4 w-full justify-center">{open}</Link></section>)}

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">{cw("overview.workflow")}</h2><div className="mt-4 space-y-3">{statusFlow.slice(0, 7).map((s) => { const current = s === claim.status; const passed = statusFlow.indexOf(s) < statusFlow.indexOf(claim.status); return <div key={s} className="flex items-center gap-3"><span className={`h-2.5 w-2.5 rounded-full ${current ? "bg-cyan-600 ring-4 ring-cyan-100" : passed ? "bg-emerald-500" : "bg-slate-200"}`} /><span className={`text-sm ${current ? "font-semibold text-slate-950" : passed ? "text-slate-600" : "text-slate-400"}`}>{statusText(s)}</span></div>; })}</div></section>

          <section className="panel p-5"><h2 className="text-sm font-semibold text-slate-950">{cw("overview.reserveControl")}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{cw("overview.reserveControlHelp")}</p><label className="mt-4 block"><span className="label">{cw("overview.amount", { currency: claim.currency })}</span><input type="number" dir="ltr" min="0" value={reserve} onChange={(e) => setReserve(e.target.value)} className="field" /></label><label className="mt-3 block"><span className="label">{cw("overview.reason")}</span><textarea rows={3} value={reserveReason} onChange={(e) => setReserveReason(e.target.value)} className="field resize-none" placeholder={cw("overview.reasonPlaceholder")} /></label><button onClick={saveReserve} disabled={updating} className="secondary-button mt-3 w-full justify-center">{updating ? cw("overview.saving") : cw("overview.saveReserve")}</button></section>
        </aside>
      </div>
    </div>
  );
}
