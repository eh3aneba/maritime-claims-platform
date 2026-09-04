"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { ApiError, getClaim, getClaimRules, getEvidenceMatrix } from "@/lib/api";
import { formatDate, formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import { reviewT } from "@/lib/i18n-review-support";
import type { Locale } from "@/lib/i18n";
import {
  getRequirementDecisionHistory,
  type RequirementDecision,
  type RequirementDecisionHistory,
} from "@/lib/requirement-lineage-api";
import type {
  Claim,
  ClaimDocumentRequirement,
  ClaimRuleSummary,
  EvidenceMatrixResponse,
  EvidenceMatrixRow,
  EvidenceMatrixSource,
  RequirementPriority,
  RequirementStatus,
} from "@/lib/types";

const priorityOrder: RequirementPriority[] = ["critical", "important", "supporting"];
const attentionRequirementStatuses = new Set<RequirementStatus>([
  "missing",
  "requested",
  "under_review",
  "rejected",
  "superseded",
]);

type RequirementWithLineage = ClaimDocumentRequirement & {
  state_fingerprint?: string | null;
  state_version?: number | null;
  latest_decision?: RequirementDecision | null;
};

function t(locale: Locale, en: string, fa: string) {
  return reviewT(locale, en, fa);
}

function requirementStatusLabel(locale: Locale, status: RequirementStatus) {
  const labels: Record<RequirementStatus, [string, string]> = {
    missing: ["Missing", "مفقود"],
    requested: ["Requested", "درخواست‌شده"],
    received: ["Received", "دریافت‌شده"],
    under_review: ["Under review", "در حال بازبینی"],
    accepted: ["Accepted", "پذیرفته‌شده"],
    rejected: ["Rejected", "ردشده"],
    superseded: ["Superseded", "منسوخ / جایگزین‌شده"],
    not_required: ["Not required", "لازم نیست"],
  };
  return t(locale, ...labels[status]);
}

function requirementStatusDetail(locale: Locale, status: RequirementStatus) {
  const details: Record<RequirementStatus, [string, string]> = {
    missing: [
      "No currently usable evidence satisfies this requirement.",
      "در حال حاضر هیچ شاهد قابل‌استفاده‌ای این نیاز را برآورده نمی‌کند.",
    ],
    requested: [
      "A controlled request is active; request status alone does not satisfy readiness.",
      "درخواست کنترل‌شده فعال است؛ صرفِ درخواست‌شدن، آمادگی شواهد را تکمیل نمی‌کند.",
    ],
    received: [
      "Evidence has been received; readiness follows the deterministic usability state.",
      "شاهد دریافت شده است؛ آمادگی بر اساس وضعیت قطعیِ قابل‌استفاده بودن تعیین می‌شود.",
    ],
    under_review: [
      "Evidence is in review and is not treated as a final human disposition.",
      "شاهد در حال بازبینی است و هنوز تصمیم نهایی انسانی محسوب نمی‌شود.",
    ],
    accepted: [
      "Current evidence has a controlled accepted basis for this requirement.",
      "شاهد فعلی برای این نیاز، مبنای پذیرش کنترل‌شده دارد.",
    ],
    rejected: [
      "A prior candidate or disposition was rejected; the requirement remains unresolved.",
      "نامزد یا تصمیم قبلی رد شده و نیاز همچنان حل‌نشده است.",
    ],
    superseded: [
      "The prior evidence/disposition is stale; explicit human re-review is required.",
      "شاهد یا تصمیم قبلی منسوخ شده و بازبینی صریح انسانی لازم است.",
    ],
    not_required: [
      "The current deterministic rule state does not require this item.",
      "بر اساس وضعیت فعلی قواعد قطعی، این مورد لازم نیست.",
    ],
  };
  return t(locale, ...details[status]);
}

function requirementTone(status: RequirementStatus) {
  if (status === "accepted" || status === "received") return "bg-emerald-50 text-emerald-800";
  if (status === "under_review" || status === "requested") return "bg-cyan-50 text-cyan-800";
  if (status === "rejected") return "bg-red-50 text-red-800";
  if (status === "not_required") return "bg-slate-100 text-slate-700";
  return "bg-amber-50 text-amber-800";
}

function priorityLabel(locale: Locale, priority: RequirementPriority) {
  if (priority === "critical") return t(locale, "Critical", "حیاتی");
  if (priority === "important") return t(locale, "Important", "مهم");
  return t(locale, "Supporting", "تکمیلی");
}

function readinessLabel(locale: Locale, state: string) {
  if (state === "ready") return t(locale, "Ready", "آماده");
  if (state === "limited") return t(locale, "Limited", "محدود");
  return t(locale, "Not ready", "آماده نیست");
}

function matrixStatusMeta(locale: Locale, status: EvidenceMatrixRow["status"]) {
  const meta: Record<
    EvidenceMatrixRow["status"],
    { className: string; en: string; fa: string; detailEn: string; detailFa: string }
  > = {
    supported: {
      className: "bg-emerald-50 text-emerald-800",
      en: "Supported",
      fa: "پشتیبانی‌شده",
      detailEn: "Approved fact supported by its current reviewed source.",
      detailFa: "واقعیت تأییدشده توسط منبع بازبینی‌شده فعلی پشتیبانی می‌شود.",
    },
    conflict_open: {
      className: "bg-red-50 text-red-800",
      en: "Conflict open",
      fa: "تعارض باز",
      detailEn: "Human review is required; the matrix does not decide which source is true.",
      detailFa: "بازبینی انسانی لازم است؛ ماتریس درباره درست‌بودن یکی از منابع تصمیم نمی‌گیرد.",
    },
    conflict_reviewed: {
      className: "bg-cyan-50 text-cyan-800",
      en: "Conflict reviewed",
      fa: "تعارض بازبینی‌شده",
      detailEn: "Related conflict has a recorded human review outcome.",
      detailFa: "برای تعارض مرتبط، نتیجه بازبینی انسانی ثبت شده است.",
    },
    source_superseded: {
      className: "bg-amber-50 text-amber-800",
      en: "Source superseded",
      fa: "منبع منسوخ",
      detailEn: "The approved fact remains linked to an older evidence version and should be re-reviewed.",
      detailFa: "واقعیت تأییدشده هنوز به نسخه قدیمی شاهد متصل است و باید دوباره بازبینی شود.",
    },
    source_deleted: {
      className: "bg-orange-50 text-orange-800",
      en: "Source unavailable",
      fa: "منبع در دسترس نیست",
      detailEn: "The provenance record remains, but its source is no longer active.",
      detailFa: "سابقه منشأ حفظ شده اما منبع آن دیگر فعال نیست.",
    },
    unsupported: {
      className: "bg-orange-50 text-orange-800",
      en: "Source missing",
      fa: "منبع مفقود",
      detailEn: "The approved fact has no readable supporting source in this view.",
      detailFa: "در این نما، منبع پشتیبان قابل‌خواندن برای واقعیت تأییدشده وجود ندارد.",
    },
    conflict_only: {
      className: "bg-slate-100 text-slate-700",
      en: "Conflict reviewed",
      fa: "تعارض بازبینی‌شده",
      detailEn: "A reviewed conflict is retained even though no current Claim Fact is attached.",
      detailFa: "تعارض بازبینی‌شده حفظ شده حتی اگر واقعیت معتبر فعلی به آن متصل نباشد.",
    },
  };
  const item = meta[status];
  return {
    className: item.className,
    label: t(locale, item.en, item.fa),
    detail: t(locale, item.detailEn, item.detailFa),
  };
}

function sourceState(locale: Locale, source: EvidenceMatrixSource) {
  if (source.document_deleted) return t(locale, "Unavailable", "در دسترس نیست");
  return source.document_is_current
    ? t(locale, "Current", "فعلی")
    : t(locale, "Superseded", "منسوخ");
}

function SourceCard({ source, locale }: { source: EvidenceMatrixSource; locale: Locale }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-slate-900" dir="auto">
          {source.document_name}
        </span>
        <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600" dir="ltr">
          v{source.document_version} · {sourceState(locale, source)}
        </span>
        {source.authoritative ? (
          <span className="rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] font-semibold text-cyan-800">
            {t(locale, "Authoritative source", "منبع مرجع")}
          </span>
        ) : (
          <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
            {t(locale, "Corroborating source", "منبع تأییدکننده")}
          </span>
        )}
      </div>
      <p className="mt-1 text-[11px] text-slate-500" dir="auto">
        {source.document_type
          ? humanizeFieldLabel(source.document_type)
          : t(locale, "Unclassified evidence", "شاهد طبقه‌بندی‌نشده")}
        {source.source_locator_value
          ? ` · ${source.source_locator_type ?? "source"} ${source.source_locator_value}`
          : ""}
        {source.source_verified
          ? ` · ${t(locale, "Source verified", "منبع تأیید شده")}`
          : ` · ${t(locale, "Manual verification", "تأیید دستی")}`}
      </p>
      {source.source_quote ? (
        <p className="mt-2 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-600" dir="auto">
          {source.source_quote}
        </p>
      ) : null}
    </div>
  );
}

function basisLabel(locale: Locale, requirement: RequirementWithLineage) {
  if (requirement.satisfaction_basis === "equivalent_evidence") {
    return t(locale, "Equivalent evidence", "شاهد معادل");
  }
  if (requirement.matched_document_id) {
    return t(locale, "Direct document", "سند مستقیم");
  }
  return t(locale, "No current satisfaction basis", "مبنای رضایت فعلی وجود ندارد");
}

export default function EvidenceMatrixPage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => t(locale, en, fa);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [matrix, setMatrix] = useState<EvidenceMatrixResponse | null>(null);
  const [rules, setRules] = useState<ClaimRuleSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ status: number | null; detail: string } | null>(null);
  const [openHistoryId, setOpenHistoryId] = useState<string | null>(null);
  const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null);
  const [histories, setHistories] = useState<Record<string, RequirementDecisionHistory>>({});
  const [historyErrors, setHistoryErrors] = useState<Record<string, string>>({});

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [claimData, matrixData, rulesData] = await Promise.all([
        getClaim(id),
        getEvidenceMatrix(id),
        getClaimRules(id),
      ]);
      setClaim(claimData);
      setMatrix(matrixData);
      setRules(rulesData);
    } catch (reason) {
      setError({
        status: reason instanceof ApiError ? reason.status : null,
        detail:
          reason instanceof ApiError
            ? reason.detail
            : r("Evidence Matrix could not be loaded.", "ماتریس شواهد بارگذاری نشد."),
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // Claim id is the only data identity for this page; locale changes presentation only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function toggleHistory(requirement: RequirementWithLineage) {
    if (openHistoryId === requirement.id) {
      setOpenHistoryId(null);
      return;
    }
    setOpenHistoryId(requirement.id);
    if (histories[requirement.id] || historyLoadingId === requirement.id) return;

    setHistoryLoadingId(requirement.id);
    setHistoryErrors((current) => {
      const next = { ...current };
      delete next[requirement.id];
      return next;
    });
    try {
      const history = await getRequirementDecisionHistory(id, requirement.id);
      setHistories((current) => ({ ...current, [requirement.id]: history }));
    } catch (reason) {
      setHistoryErrors((current) => ({
        ...current,
        [requirement.id]:
          reason instanceof ApiError
            ? reason.detail
            : r("Decision history could not be loaded.", "تاریخچه تصمیم بارگذاری نشد."),
      }));
    } finally {
      setHistoryLoadingId(null);
    }
  }

  const activeRequirements = useMemo(
    () =>
      (rules?.requirements ?? [])
        .filter((item) => item.is_active !== false)
        .map((item) => item as RequirementWithLineage),
    [rules],
  );

  const groupedRequirements = useMemo(() => {
    const output = new Map<RequirementPriority, RequirementWithLineage[]>();
    for (const priority of priorityOrder) output.set(priority, []);
    for (const requirement of activeRequirements) {
      output.get(requirement.priority)?.push(requirement);
    }
    return output;
  }, [activeRequirements]);

  const requirementAttentionCount = useMemo(
    () => activeRequirements.filter((item) => attentionRequirementStatuses.has(item.status)).length,
    [activeRequirements],
  );

  const matrixAttentionCount = useMemo(
    () =>
      matrix?.rows.filter((row) =>
        ["conflict_open", "source_superseded", "source_deleted", "unsupported"].includes(row.status),
      ).length ?? 0,
    [matrix],
  );

  if (loading && (!claim || !matrix || !rules)) {
    return (
      <div className="py-20 text-center text-sm text-slate-500">
        {r("Loading Evidence Matrix…", "در حال بارگذاری ماتریس شواهد…")}
      </div>
    );
  }

  if (!claim || !matrix || !rules) {
    const permissionDenied = error?.status === 403;
    return (
      <div className="mx-auto max-w-2xl py-16">
        <div className="panel p-6">
          <h1 className="text-lg font-semibold text-slate-950">
            {permissionDenied
              ? r("Evidence Matrix access is restricted", "دسترسی به ماتریس شواهد محدود است")
              : r("Evidence Matrix unavailable", "ماتریس شواهد در دسترس نیست")}
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-600" dir="auto">
            {permissionDenied
              ? r(
                  "Your current claim permissions do not allow this evidence view.",
                  "مجوز فعلی شما برای این پرونده اجازه مشاهده این نمای شواهد را نمی‌دهد.",
                )
              : error?.detail || r("The page could not be loaded.", "صفحه بارگذاری نشد.")}
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {!permissionDenied ? (
              <button className="primary-button" onClick={() => void load()}>
                {r("Retry", "تلاش دوباره")}
              </button>
            ) : null}
            <Link href={`/claims/${id}`} className="secondary-button">
              {r("Back to claim", "بازگشت به پرونده")}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">
        {r("← Back to claim", "→ بازگشت به پرونده")}
      </Link>

      <div className="mt-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <p className="eyebrow" dir="ltr">{claim.claim_reference}</p>
          <h1 className="page-title">{r("Evidence Matrix", "ماتریس شواهد")}</h1>
          <p className="page-subtitle">
            {r(
              "One read-only operator view for evidence completeness, document requirements, human review lineage, approved Claim Facts, source versions and active conflicts. It does not decide causation, coverage, source truth or substitute-document sufficiency.",
              "یک نمای فقط‌خواندنی برای کامل‌بودن شواهد، نیازهای اسنادی، سابقه بازبینی انسانی، واقعیت‌های تأییدشده پرونده، نسخه‌های منابع و تعارض‌های فعال. این نما درباره علت، پوشش بیمه، حقیقت منبع یا کفایت حقوقی سند جایگزین تصمیم نمی‌گیرد.",
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="secondary-button" disabled={loading} onClick={() => void load()}>
            {loading ? r("Refreshing…", "در حال به‌روزرسانی…") : r("Refresh view", "به‌روزرسانی نما")}
          </button>
          <Link href={`/claims/${id}/rules`} className="primary-button">
            {r("Review / request evidence", "بازبینی / درخواست شواهد")}
          </Link>
        </div>
      </div>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" dir="auto">
          {error.detail}
        </div>
      ) : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <div className="panel p-5">
          <p className="metric-label">{r("Readiness", "آمادگی شواهد")}</p>
          <p className="metric-value" dir="ltr">{rules.readiness.score}%</p>
          <p className="mt-1 text-xs font-semibold text-slate-500">{readinessLabel(locale, rules.readiness.state)}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Critical missing", "موارد حیاتی مفقود")}</p>
          <p className="metric-value" dir="ltr">{rules.readiness.critical_missing_count}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Requirements needing attention", "نیازهای محتاج اقدام")}</p>
          <p className="metric-value" dir="ltr">{requirementAttentionCount}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Approved facts", "واقعیت‌های تأییدشده")}</p>
          <p className="metric-value" dir="ltr">{matrix.summary.approved_fact_count}</p>
          <p className="mt-1 text-xs text-slate-400">
            {r("Reviewed sources", "منابع بازبینی‌شده")}: {matrix.summary.supporting_source_count}
          </p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">{r("Open conflicts", "تعارض‌های باز")}</p>
          <p className="metric-value" dir="ltr">{matrix.summary.open_conflict_count}</p>
          <p className="mt-1 text-xs text-slate-400">
            {r("Matrix attention", "موارد نیازمند توجه در ماتریس")}: {matrixAttentionCount}
          </p>
        </div>
      </section>

      {rules.readiness.blocking_items.length ? (
        <section className="mt-5 rounded-xl border border-red-200 bg-red-50 p-5">
          <h2 className="text-sm font-semibold text-red-900">{r("Blocking evidence", "شواهد مسدودکننده")}</h2>
          <p className="mt-1 text-xs leading-5 text-red-700">
            {r(
              "Requested, processing, rejected or stale evidence remains blocking until the deterministic requirement state becomes usable/accepted or is explicitly no longer required.",
              "شاهد درخواست‌شده، در حال پردازش، ردشده یا منسوخ تا زمانی که وضعیت قطعی نیاز به حالت قابل‌استفاده/پذیرفته برسد یا صراحتاً دیگر لازم نباشد، مسدودکننده باقی می‌ماند.",
            )}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {rules.readiness.blocking_items.map((item) => (
              <span key={item} className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-red-700 ring-1 ring-red-200" dir="auto">
                {item}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <section className="panel mt-6 overflow-hidden" aria-labelledby="requirements-heading">
        <div className="border-b border-slate-200 px-6 py-5">
          <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
            <div>
              <h2 id="requirements-heading" className="section-title">{r("Requirements & readiness", "نیازها و آمادگی شواهد")}</h2>
              <p className="section-subtitle">
                {r(
                  "Current deterministic requirement state with direct/equivalent evidence context. Historical human decisions are append-only and remain distinguishable from the current evidence state.",
                  "وضعیت فعلی و قطعی نیازها همراه با زمینه سند مستقیم یا شاهد معادل. تصمیم‌های تاریخی انسانی به‌صورت افزایشی حفظ می‌شوند و از وضعیت فعلی شواهد قابل‌تفکیک‌اند.",
                )}
              </p>
            </div>
            <p className="text-xs text-slate-400" dir="ltr">
              {rules.ruleset_name} · v{rules.ruleset_version}
            </p>
          </div>
        </div>

        {activeRequirements.length ? (
          <div className="space-y-7 p-6">
            {priorityOrder.map((priority) => {
              const items = groupedRequirements.get(priority) ?? [];
              if (!items.length) return null;
              return (
                <div key={priority}>
                  <div className="mb-3 flex items-center gap-2">
                    <h3 className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">
                      {priorityLabel(locale, priority)}
                    </h3>
                    <span className="text-xs text-slate-400" dir="ltr">{items.length}</span>
                  </div>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {items.map((requirement) => {
                      const history = histories[requirement.id];
                      const latestDecision = requirement.latest_decision ?? history?.items.at(-1) ?? null;
                      const historyOpen = openHistoryId === requirement.id;
                      return (
                        <article key={requirement.id} className="rounded-xl border border-slate-200 bg-white p-4" data-requirement-id={requirement.id}>
                          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <h4 className="text-sm font-semibold text-slate-950" dir="auto">{requirement.document_label}</h4>
                                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${requirementTone(requirement.status)}`}>
                                  {requirementStatusLabel(locale, requirement.status)}
                                </span>
                                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                                  {basisLabel(locale, requirement)}
                                </span>
                              </div>
                              <p className="mt-2 text-xs leading-5 text-slate-500" dir="auto">{requirement.reason}</p>
                            </div>
                            <div className="shrink-0 text-[11px] text-slate-400" dir="ltr">
                              <div>{requirement.rule_id} · v{requirement.rule_version}</div>
                              {requirement.state_version ? <div>Evidence state v{requirement.state_version}</div> : null}
                            </div>
                          </div>

                          <div className="mt-3 rounded-lg bg-slate-50 p-3">
                            <p className="text-xs leading-5 text-slate-600">{requirementStatusDetail(locale, requirement.status)}</p>
                            {requirement.satisfaction_note ? (
                              <p className="mt-2 text-xs leading-5 text-violet-700" dir="auto">
                                <span className="font-semibold">{r("Recorded basis", "مبنای ثبت‌شده")}:</span> {requirement.satisfaction_note}
                              </p>
                            ) : null}
                            {requirement.satisfaction_basis === "equivalent_evidence" ? (
                              <p className="mt-2 text-xs leading-5 text-violet-700">
                                {r(
                                  "Equivalent evidence was accepted by a human reviewer; this view does not infer legal sufficiency from that decision.",
                                  "شاهد معادل توسط بازبین انسانی پذیرفته شده است؛ این نما از آن تصمیم، کفایت حقوقی را استنباط نمی‌کند.",
                                )}
                              </p>
                            ) : requirement.matched_document_id ? (
                              <p className="mt-2 text-xs leading-5 text-emerald-700">
                                {r(
                                  "A current direct document is linked to this requirement.",
                                  "یک سند مستقیم فعلی به این نیاز متصل است.",
                                )}
                              </p>
                            ) : null}
                          </div>

                          {latestDecision ? (
                            <div className="mt-3 rounded-lg border border-violet-100 bg-violet-50/60 p-3">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="text-[11px] font-bold uppercase tracking-[.12em] text-violet-700">
                                  {r("Latest human decision", "آخرین تصمیم انسانی")} #{latestDecision.decision_number}
                                </p>
                                <span className="text-[11px] text-violet-500" dir="ltr">{formatDate(latestDecision.decided_at)}</span>
                              </div>
                              <p className="mt-1 text-xs font-semibold text-slate-800">
                                {humanizeFieldLabel(latestDecision.action)}
                                {latestDecision.claim_fact_version ? ` · Claim Fact v${latestDecision.claim_fact_version}` : ""}
                                {latestDecision.source_document_version ? ` · Source v${latestDecision.source_document_version}` : ""}
                              </p>
                              <p className="mt-1 text-xs leading-5 text-slate-600" dir="auto">{latestDecision.note}</p>
                            </div>
                          ) : null}

                          {(requirement.state_version || latestDecision) ? (
                            <div className="mt-3">
                              <button className="text-xs font-semibold text-cyan-700 hover:text-cyan-900" onClick={() => void toggleHistory(requirement)}>
                                {historyOpen
                                  ? r("Hide decision lineage", "بستن سابقه تصمیم")
                                  : r("View decision lineage", "مشاهده سابقه تصمیم")}
                              </button>
                              {historyOpen ? (
                                <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                                  {historyLoadingId === requirement.id ? (
                                    <p className="text-xs text-slate-500">{r("Loading decision lineage…", "در حال بارگذاری سابقه تصمیم…")}</p>
                                  ) : historyErrors[requirement.id] ? (
                                    <div>
                                      <p className="text-xs text-red-700" dir="auto">{historyErrors[requirement.id]}</p>
                                      <Link href={`/claims/${id}/rules`} className="mt-2 inline-block text-xs font-semibold text-cyan-700">
                                        {r("Refresh / re-review in Rules", "به‌روزرسانی / بازبینی مجدد در Rules")}
                                      </Link>
                                    </div>
                                  ) : history?.items.length ? (
                                    <ol className="space-y-2">
                                      {history.items.map((decision) => (
                                        <li key={decision.id} className="rounded-md bg-white p-3 ring-1 ring-slate-200">
                                          <div className="flex flex-wrap items-center justify-between gap-2">
                                            <p className="text-xs font-semibold text-slate-800">
                                              #{decision.decision_number} · {humanizeFieldLabel(decision.action)}
                                            </p>
                                            <span className="text-[11px] text-slate-400" dir="ltr">{formatDate(decision.decided_at)}</span>
                                          </div>
                                          <p className="mt-1 text-xs leading-5 text-slate-600" dir="auto">{decision.note}</p>
                                          <p className="mt-1 text-[11px] text-slate-400" dir="ltr">
                                            state v{decision.state_version}
                                            {decision.claim_fact_version ? ` · Claim Fact v${decision.claim_fact_version}` : ""}
                                            {decision.source_document_version ? ` · Source v${decision.source_document_version}` : ""}
                                          </p>
                                        </li>
                                      ))}
                                    </ol>
                                  ) : (
                                    <p className="text-xs text-slate-500">
                                      {r("No human decision has been recorded for this evidence state yet.", "هنوز تصمیم انسانی برای این وضعیت شواهد ثبت نشده است.")}
                                    </p>
                                  )}
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="p-10 text-center">
            <p className="text-sm font-semibold text-slate-700">
              {r("No active document requirements for the current claim stage.", "برای مرحله فعلی پرونده، نیاز سندی فعالی وجود ندارد.")}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {r("Refresh Rules after the claim stage or evidence changes.", "پس از تغییر مرحله پرونده یا شواهد، Rules را به‌روزرسانی کنید.")}
            </p>
          </div>
        )}
      </section>

      <section className="panel mt-6 overflow-hidden" aria-labelledby="facts-heading">
        <div className="border-b border-slate-200 px-6 py-5">
          <h2 id="facts-heading" className="section-title">{r("Facts, sources & conflicts", "واقعیت‌ها، منابع و تعارض‌ها")}</h2>
          <p className="section-subtitle">
            {r(
              "Current and historical evidence remain distinguishable. Approval never transfers automatically when a source document is replaced.",
              "شواهد فعلی و تاریخی از یکدیگر قابل‌تفکیک می‌مانند. با جایگزینی سند منبع، تأیید به‌صورت خودکار منتقل نمی‌شود.",
            )}
          </p>
        </div>

        {matrix.rows.length ? (
          <div className="overflow-x-auto">
            <table className="data-table min-w-[1180px]">
              <thead>
                <tr>
                  <th className="w-[190px]">{r("Topic", "موضوع")}</th>
                  <th className="w-[220px]">{r("Fact", "واقعیت")}</th>
                  <th className="w-[340px]">{r("Supporting evidence", "شواهد پشتیبان")}</th>
                  <th className="w-[300px]">{r("Conflicting evidence", "شواهد متعارض")}</th>
                  <th className="w-[170px]">{r("Status", "وضعیت")}</th>
                </tr>
              </thead>
              <tbody>
                {matrix.rows.map((row) => {
                  const meta = matrixStatusMeta(locale, row.status);
                  return (
                    <tr key={row.row_key} className="align-top">
                      <td>
                        <p className="font-semibold text-slate-900" dir="auto">{row.topic}</p>
                        {row.field_path ? (
                          <p className="mt-1 text-[11px] text-slate-400" dir="ltr">{humanizeFieldLabel(row.field_path)}</p>
                        ) : (
                          <p className="mt-1 text-[11px] text-slate-400">{r("Conflict-only review item", "مورد بازبینی صرفاً تعارضی")}</p>
                        )}
                      </td>
                      <td>
                        {row.fact_id ? (
                          <>
                            <p className="break-words text-sm font-semibold text-slate-900" dir="auto">{formatStructuredValue(row.fact_value)}</p>
                            <p className="mt-2 text-[11px] text-slate-500" dir="ltr">
                              Claim Fact v{row.fact_version}
                              {row.approved_at ? ` · ${r("approved", "تأیید")}: ${formatDate(row.approved_at)}` : ""}
                            </p>
                          </>
                        ) : (
                          <p className="text-sm text-slate-500">{r("No authoritative Claim Fact", "واقعیت معتبر پرونده وجود ندارد")}</p>
                        )}
                      </td>
                      <td>
                        {row.supporting_evidence.length ? (
                          <div className="space-y-2">
                            {row.supporting_evidence.map((source) => (
                              <SourceCard key={source.extraction_id} source={source} locale={locale} />
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">{r("No reviewed source available.", "منبع بازبینی‌شده‌ای موجود نیست.")}</p>
                        )}
                      </td>
                      <td>
                        {row.conflicting_evidence.length ? (
                          <div className="space-y-2">
                            {row.conflicting_evidence.map((conflict) => (
                              <div key={conflict.id} className="rounded-lg border border-red-100 bg-red-50/60 p-3">
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="text-xs font-semibold text-red-950" dir="auto">{conflict.topic}</p>
                                  <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold uppercase text-red-700">
                                    {humanizeFieldLabel(conflict.status)}
                                  </span>
                                </div>
                                <p className="mt-2 text-xs leading-5 text-slate-600" dir="auto">{conflict.description}</p>
                                <div className="mt-2 space-y-1 text-[11px] text-slate-600">
                                  <p><span className="font-semibold">A:</span> <span dir="auto">{formatStructuredValue(conflict.value_a)}</span></p>
                                  <p><span className="font-semibold">B:</span> <span dir="auto">{formatStructuredValue(conflict.value_b)}</span></p>
                                  {conflict.difference_minutes ? (
                                    <p><span className="font-semibold">{r("Difference", "اختلاف")}:</span> <span dir="ltr">{conflict.difference_minutes} {r("minutes", "دقیقه")}</span></p>
                                  ) : null}
                                </div>
                                {conflict.resolution_note ? (
                                  <p className="mt-2 border-t border-red-100 pt-2 text-[11px] leading-5 text-slate-600" dir="auto">
                                    {r("Human review", "بازبینی انسانی")}: {conflict.resolution_note}
                                  </p>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">{r("No active conflict linked.", "تعارض فعالی متصل نیست.")}</p>
                        )}
                      </td>
                      <td>
                        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${meta.className}`}>{meta.label}</span>
                        <p className="mt-2 text-xs leading-5 text-slate-500">{meta.detail}</p>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-10 text-center">
            <p className="text-sm font-semibold text-slate-700">
              {r("No reviewed facts or conflicts are available yet.", "هنوز واقعیت بازبینی‌شده یا تعارضی موجود نیست.")}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {r(
                "Review source-linked AI evidence and current document requirements to populate this provenance view.",
                "برای تکمیل این نمای منشأ، شواهد AI متصل به منبع و نیازهای اسنادی فعلی را بازبینی کنید.",
              )}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
