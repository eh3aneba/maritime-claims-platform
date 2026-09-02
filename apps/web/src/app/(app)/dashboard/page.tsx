"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PriorityText, StatusBadge } from "@/components/status-badge";
import { useLocale } from "@/components/locale-provider";
import { ApiError, listClaims } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { Claim } from "@/lib/types";

const GENERIC_ERROR = "__dashboard_generic_error__";

export default function DashboardPage() {
  const { locale, t } = useLocale();
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    listClaims(new URLSearchParams({ limit: "100" }))
      .then((result) => { setClaims(result.items); setError(""); })
      .catch((err) => setError(err instanceof ApiError ? err.detail : GENERIC_ERROR))
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const open = claims.filter((c) => !["closed", "rejected", "withdrawn"].includes(c.status));
    const reserveClaims = open.filter((c) => c.current_reserve !== null);
    const reserveCurrencies = new Set(reserveClaims.map((c) => c.currency));
    const reserve = reserveClaims.reduce((sum, c) => sum + Number(c.current_reserve ?? 0), 0);
    const reserveDisplay = reserveCurrencies.size > 1
      ? t("dashboard.mixedCurrencies")
      : formatMoney(reserve, reserveClaims[0]?.currency ?? "USD", locale);
    const urgent = open.filter((c) => ["high", "critical"].includes(c.priority));
    const unassigned = open.filter((c) => !c.handler);
    return { open: open.length, reserveDisplay, urgent: urgent.length, unassigned: unassigned.length };
  }, [claims, locale, t]);

  const cards = [
    { label: t("dashboard.metric.openClaims"), value: loading ? "—" : String(stats.open), hint: t("dashboard.metric.openHint") },
    { label: t("dashboard.metric.currentReserve"), value: loading ? "—" : stats.reserveDisplay, hint: t("dashboard.metric.reserveHint") },
    { label: t("dashboard.metric.highPriority"), value: loading ? "—" : String(stats.urgent), hint: t("dashboard.metric.priorityHint") },
    { label: t("dashboard.metric.unassigned"), value: loading ? "—" : String(stats.unassigned), hint: t("dashboard.metric.unassignedHint") },
  ];

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">{t("dashboard.eyebrow")}</p>
          <h1 className="page-title">{t("dashboard.title")}</h1>
          <p className="page-subtitle">{t("dashboard.description")}</p>
        </div>
        <Link href="/claims/new" className="primary-button">{t("dashboard.newClaim")}</Link>
      </div>

      {error ? <div className="mt-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error === GENERIC_ERROR ? t("dashboard.loadError") : error}</div> : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <article key={card.label} className="panel p-5">
            <p className="text-sm font-medium text-slate-500">{card.label}</p>
            <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950" dir="ltr">{card.value}</p>
            <p className="mt-2 text-xs text-slate-400">{card.hint}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-950">{t("dashboard.recentClaims")}</h2>
            <p className="mt-1 text-sm text-slate-500">{t("dashboard.recentHelp")}</p>
          </div>
          <Link href="/claims" className="text-sm font-semibold text-cyan-800 hover:text-cyan-700">{t("dashboard.viewAll")}</Link>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>{t("dashboard.column.claim")}</th><th>{t("dashboard.column.vessel")}</th><th>{t("dashboard.column.incident")}</th><th>{t("dashboard.column.status")}</th><th>{t("dashboard.column.priority")}</th><th>{t("dashboard.column.reserve")}</th></tr></thead>
            <tbody>
              {!loading && claims.length === 0 ? <tr><td colSpan={6} className="py-12 text-center text-slate-500">{t("dashboard.empty")}</td></tr> : null}
              {claims.slice(0, 6).map((claim) => (
                <tr key={claim.id}>
                  <td><Link className="font-semibold text-slate-950 hover:text-cyan-800" href={`/claims/${claim.id}`} dir="ltr">{claim.claim_reference}</Link></td>
                  <td><div className="font-medium text-slate-800">{claim.vessel.name}</div><div className="text-xs text-slate-400" dir="ltr">{claim.vessel.imo_number ? `IMO ${claim.vessel.imo_number}` : t("dashboard.imoNotRecorded")}</div></td>
                  <td>{formatDate(claim.incident_date, locale)}</td>
                  <td><StatusBadge status={claim.status} /></td>
                  <td><PriorityText priority={claim.priority} /></td>
                  <td dir="ltr">{formatMoney(claim.current_reserve, claim.currency, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
