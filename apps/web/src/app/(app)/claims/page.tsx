"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { PriorityText, StatusBadge } from "@/components/status-badge";
import { useLocale } from "@/components/locale-provider";
import { ApiError, listClaims } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { TranslationKey } from "@/lib/i18n";
import type { Claim, ClaimPriority, ClaimStatus } from "@/lib/types";

const GENERIC_ERROR = "__claims_generic_error__";
const statuses: ClaimStatus[] = ["new","triage","awaiting_documents","investigation","technical_review","financial_review","coverage_review","negotiation","settlement","recovery","closed","on_hold","litigation","rejected","withdrawn"];
const priorities: ClaimPriority[] = ["low","medium","high","critical"];

const statusKeys: Record<ClaimStatus, TranslationKey> = {
  new: "status.new",
  triage: "status.triage",
  awaiting_documents: "status.awaiting_documents",
  investigation: "status.investigation",
  technical_review: "status.technical_review",
  financial_review: "status.financial_review",
  coverage_review: "status.coverage_review",
  negotiation: "status.negotiation",
  settlement: "status.settlement",
  recovery: "status.recovery",
  closed: "status.closed",
  on_hold: "status.on_hold",
  litigation: "status.litigation",
  rejected: "status.rejected",
  withdrawn: "status.withdrawn",
};
const priorityKeys: Record<ClaimPriority, TranslationKey> = {
  low: "priority.low",
  medium: "priority.medium",
  high: "priority.high",
  critical: "priority.critical",
};

export default function ClaimsPage() {
  const { locale, t } = useLocale();
  const [items, setItems] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(params = new URLSearchParams()) {
    setLoading(true);
    try {
      params.set("limit", "100");
      const result = await listClaims(params);
      setItems(result.items);
      setTotal(result.total);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : GENERIC_ERROR);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  function filter(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    void load(params);
  }

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div><p className="eyebrow">{t("claims.eyebrow")}</p><h1 className="page-title">{t("claims.title")}</h1><p className="page-subtitle">{t("claims.description")}</p></div>
        <Link href="/claims/new" className="primary-button">{t("claims.newClaim")}</Link>
      </div>

      {error ? <div className="mt-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error === GENERIC_ERROR ? t("claims.loadError") : error}</div> : null}

      <form onSubmit={filter} className="panel mt-7 grid gap-3 p-4 md:grid-cols-[1fr_220px_180px_auto]">
        <input value={search} onChange={(e) => setSearch(e.target.value)} className="field" placeholder={t("claims.searchPlaceholder")} />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="field"><option value="">{t("claims.allStatuses")}</option>{statuses.map((s) => <option key={s} value={s}>{t(statusKeys[s])}</option>)}</select>
        <select value={priority} onChange={(e) => setPriority(e.target.value)} className="field"><option value="">{t("claims.allPriorities")}</option>{priorities.map((p) => <option key={p} value={p}>{t(priorityKeys[p])}</option>)}</select>
        <button className="secondary-button">{t("claims.applyFilters")}</button>
      </form>

      <section className="panel mt-5 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4"><p className="text-sm text-slate-500">{loading ? t("common.loading") : total === 1 ? t("claims.count.one") : t("claims.count.many", { count: total })}</p></div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>{t("claims.column.claim")}</th><th>{t("claims.column.vessel")}</th><th>{t("claims.column.incident")}</th><th>{t("claims.column.status")}</th><th>{t("claims.column.priority")}</th><th>{t("claims.column.estimate")}</th><th>{t("claims.column.reserve")}</th><th>{t("claims.column.handler")}</th><th>{t("claims.column.intelligence")}</th></tr></thead>
            <tbody>
              {!loading && items.length === 0 ? <tr><td colSpan={9} className="py-14 text-center text-slate-500">{t("claims.empty")}</td></tr> : null}
              {items.map((claim) => <tr key={claim.id}>
                <td><Link href={`/claims/${claim.id}`} className="font-semibold text-slate-950 hover:text-cyan-800" dir="ltr">{claim.claim_reference}</Link>{claim.external_reference ? <div className="mt-1 text-xs text-slate-400" dir="ltr">{claim.external_reference}</div> : null}</td>
                <td><div className="font-medium text-slate-800">{claim.vessel.name}</div><div className="text-xs text-slate-400" dir="ltr">{claim.vessel.imo_number ? `IMO ${claim.vessel.imo_number}` : "—"}</div></td>
                <td>{formatDate(claim.incident_date, locale)}</td><td><StatusBadge status={claim.status} /></td><td><PriorityText priority={claim.priority} /></td>
                <td dir="ltr">{formatMoney(claim.estimated_loss, claim.currency, locale)}</td><td dir="ltr">{formatMoney(claim.current_reserve, claim.currency, locale)}</td><td>{claim.handler?.full_name ?? <span className="text-slate-400">{t("common.unassigned")}</span>}</td>
                <td><Link href={`/claims/${claim.id}/intelligence`} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">{t("claims.openIntelligence")}</Link></td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
