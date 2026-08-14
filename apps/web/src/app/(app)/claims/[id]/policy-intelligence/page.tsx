"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  extractPolicyTerms,
  getClaim,
  getPolicyIntelligence,
  listClaimDocuments,
} from "@/lib/api";
import type {
  Claim,
  ClaimDocument,
  PolicyIntelligenceResponse,
  ReviewedPolicyTerm,
} from "@/lib/types";

const policyDocumentTypes = new Set([
  "policy",
  "policy_wording",
  "hm_policy",
  "h&m_policy",
  "insurance_contract",
  "charter_party",
  "contract",
  "endorsement",
]);

const severityStyle: Record<string, string> = {
  critical: "border-red-200 bg-red-50 text-red-800",
  high: "border-orange-200 bg-orange-50 text-orange-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  low: "border-sky-200 bg-sky-50 text-sky-800",
  info: "border-slate-200 bg-slate-50 text-slate-700",
};

function termText(term: ReviewedPolicyTerm): string {
  const value = term.value;
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return String(value ?? "Not established");
  }
  const structured = value as Record<string, unknown>;
  if (typeof structured.text === "string") return structured.text;
  const amount =
    typeof structured.currency === "string" &&
    typeof structured.amount === "string"
      ? structured.currency + " " + structured.amount
      : null;
  const percentage =
    typeof structured.percentage === "string"
      ? structured.percentage + "%"
      : null;
  return [amount, percentage].filter(Boolean).join(" · ") || "Reviewed term";
}

function locator(term: ReviewedPolicyTerm): string {
  const type = term.source.source_locator_type;
  const value = term.source.source_locator_value;
  if (!type && !value) return "Location not recorded";
  return [type, value].filter(Boolean).join(" ");
}

export default function PolicyIntelligencePage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [intelligence, setIntelligence] =
    useState<PolicyIntelligenceResponse | null>(null);
  const [documents, setDocuments] = useState<ClaimDocument[]>([]);
  const [extracting, setExtracting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    try {
      const [claimRow, policyView, documentRows] = await Promise.all([
        getClaim(id),
        getPolicyIntelligence(id),
        listClaimDocuments(id),
      ]);
      setClaim(claimRow);
      setIntelligence(policyView);
      setDocuments(documentRows.items);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : "Policy intelligence could not be loaded.",
      );
    }
  }

  useEffect(() => {
    load();
  }, [id]);

  const policyDocuments = useMemo(
    () =>
      documents.filter(
        (document) =>
          document.is_current &&
          policyDocumentTypes.has((document.document_type ?? "").toLowerCase()),
      ),
    [documents],
  );

  const groupedTerms = useMemo(() => {
    const groups = new Map<string, ReviewedPolicyTerm[]>();
    for (const term of intelligence?.terms ?? []) {
      const existing = groups.get(term.category) ?? [];
      existing.push(term);
      groups.set(term.category, existing);
    }
    return Array.from(groups.entries());
  }, [intelligence]);

  async function runExtraction(document: ClaimDocument) {
    setExtracting(document.id);
    setError("");
    setNotice("");
    try {
      const result = await extractPolicyTerms(id, document.id);
      setNotice(
        String(result.candidate_count) +
          " source-linked candidates were added to Human Review. Nothing has become an approved policy term yet.",
      );
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : "Local policy extraction could not be completed.",
      );
    } finally {
      setExtracting(null);
    }
  }

  if (!intelligence && !error) {
    return (
      <div className="py-20 text-center text-sm text-slate-500">
        Loading policy intelligence…
      </div>
    );
  }

  return (
    <div>
      <Link
        href={"/claims/" + id}
        className="text-sm font-semibold text-slate-500 hover:text-slate-800"
      >
        ← Back to claim
      </Link>

      <div className="mt-5">
        <p className="eyebrow">{claim?.claim_reference ?? "Claim workspace"}</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">
          Policy &amp; Contract Intelligence
        </h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">
          Review source-linked policy terms and investigation prompts without
          turning extracted wording into an automated coverage decision.
        </p>
      </div>

      <section className="mt-7 rounded-xl border border-cyan-200 bg-cyan-50 p-5">
        <h2 className="text-sm font-semibold text-cyan-950">
          Issue spotting only
        </h2>
        <p className="mt-2 text-sm leading-6 text-cyan-900">
          {intelligence?.disclaimer ??
            "This workspace supports human review and does not decide coverage."}
        </p>
      </section>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}{" "}
          <Link
            href={"/ai-review?claim_id=" + id}
            className="font-semibold underline"
          >
            Review candidates
          </Link>
        </div>
      ) : null}

      {intelligence ? (
        <>
          <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="panel p-5">
              <p className="metric-label">Reviewed terms</p>
              <p className="metric-value">{intelligence.summary.reviewed_term_count}</p>
            </div>
            <div className="panel p-5">
              <p className="metric-label">Current policy sources</p>
              <p className="metric-value">
                {intelligence.summary.current_policy_document_count}
              </p>
            </div>
            <div className="panel p-5">
              <p className="metric-label">Issue spots</p>
              <p className="metric-value">{intelligence.summary.issue_count}</p>
            </div>
            <div className="panel p-5">
              <p className="metric-label">High priority</p>
              <p className="metric-value text-orange-700">
                {intelligence.summary.high_priority_issue_count}
              </p>
            </div>
          </section>

          <section className="panel mt-6 p-6">
            <div>
              <h2 className="section-title">Policy source processing</h2>
              <p className="section-subtitle">
                Local rules create pending candidates with exact source quotes.
                Every candidate still requires field-level Human Review.
              </p>
            </div>
            {policyDocuments.length ? (
              <div className="mt-5 space-y-3">
                {policyDocuments.map((document) => (
                  <div
                    key={document.id}
                    className="flex flex-col justify-between gap-3 rounded-lg border border-slate-200 p-4 sm:flex-row sm:items-center"
                  >
                    <div>
                      <p className="font-medium text-slate-900">
                        {document.original_filename}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {(document.document_type ?? "Policy source").replaceAll(
                          "_",
                          " ",
                        )}{" "}
                        · version {document.version_number} ·{" "}
                        {document.processing_status}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={extracting !== null}
                      onClick={() => runExtraction(document)}
                      className="secondary-button justify-center"
                    >
                      {extracting === document.id
                        ? "Extracting…"
                        : "Create review candidates"}
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-5 rounded-lg border border-dashed border-amber-300 bg-amber-50 px-5 py-8 text-center text-sm text-amber-900">
                No current document is classified as a supported policy or
                contract source. Upload and classify the complete wording and
                endorsements first.
              </div>
            )}
          </section>

          <section className="panel mt-6 p-6">
            <div>
              <h2 className="section-title">Issue spots requiring human judgment</h2>
              <p className="section-subtitle">
                Each prompt states why it appeared and what a qualified reviewer
                must verify.
              </p>
            </div>
            <div className="mt-5 space-y-4">
              {intelligence.issue_spots.map((issue) => (
                <article
                  key={issue.code}
                  className={"rounded-lg border p-4 " + severityStyle[issue.severity]}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-current px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
                      {issue.severity}
                    </span>
                    <h3 className="font-semibold">{issue.title}</h3>
                  </div>
                  <p className="mt-2 text-sm leading-6">{issue.description}</p>
                  <p className="mt-3 text-sm font-semibold">Human action</p>
                  <p className="mt-1 text-sm leading-6">
                    {issue.required_human_action}
                  </p>
                </article>
              ))}
              {!intelligence.issue_spots.length ? (
                <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center text-sm text-slate-500">
                  No rule-based review prompts are currently open. This is not a
                  coverage confirmation.
                </p>
              ) : null}
            </div>
          </section>

          <section className="panel mt-6 p-6">
            <div>
              <h2 className="section-title">Human-reviewed term register</h2>
              <p className="section-subtitle">
                Approved or edited terms only, with document version, location
                and source quotation.
              </p>
            </div>
            {groupedTerms.length ? (
              <div className="mt-5 space-y-6">
                {groupedTerms.map(([category, terms]) => (
                  <div key={category}>
                    <h3 className="text-sm font-semibold text-slate-950">
                      {terms[0].title}
                    </h3>
                    <div className="mt-3 grid gap-3 xl:grid-cols-2">
                      {terms.map((term) => (
                        <article
                          key={term.extraction_id}
                          className="rounded-lg border border-slate-200 p-4"
                        >
                          <p className="text-sm font-medium leading-6 text-slate-900">
                            {termText(term)}
                          </p>
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                            <span>{term.source.document_name}</span>
                            <span>· v{term.source.document_version}</span>
                            <span>
                              ·{" "}
                              {term.source.document_is_current
                                ? "current source"
                                : "superseded source"}
                            </span>
                            <span>· {locator(term)}</span>
                          </div>
                          {term.source.source_quote ? (
                            <blockquote className="mt-3 border-l-2 border-cyan-500 pl-3 text-xs leading-5 text-slate-600">
                              {term.source.source_quote}
                            </blockquote>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-5 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-5 py-10 text-center text-sm text-slate-500">
                No policy or contract term has completed Human Review yet.
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
