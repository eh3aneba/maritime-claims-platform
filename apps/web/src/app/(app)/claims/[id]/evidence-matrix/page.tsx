"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, getClaim, getEvidenceMatrix } from "@/lib/api";
import { formatStructuredValue, humanizeFieldLabel } from "@/lib/format";
import type {
  Claim,
  EvidenceMatrixResponse,
  EvidenceMatrixRow,
  EvidenceMatrixSource,
} from "@/lib/types";

const statusMeta: Record<
  EvidenceMatrixRow["status"],
  { label: string; className: string; detail: string }
> = {
  supported: {
    label: "Supported",
    className: "bg-emerald-50 text-emerald-800",
    detail: "Approved fact supported by its current reviewed source.",
  },
  conflict_open: {
    label: "Conflict open",
    className: "bg-red-50 text-red-800",
    detail: "Human review is required; the matrix does not decide which source is true.",
  },
  conflict_reviewed: {
    label: "Conflict reviewed",
    className: "bg-cyan-50 text-cyan-800",
    detail: "Related conflict has a recorded human review outcome.",
  },
  source_superseded: {
    label: "Source superseded",
    className: "bg-amber-50 text-amber-800",
    detail: "The approved fact remains linked to an older evidence version and should be re-reviewed.",
  },
  source_deleted: {
    label: "Source unavailable",
    className: "bg-orange-50 text-orange-800",
    detail: "The provenance record remains, but its source is no longer active.",
  },
  unsupported: {
    label: "Source missing",
    className: "bg-orange-50 text-orange-800",
    detail: "The approved fact has no readable supporting source in this view.",
  },
  conflict_only: {
    label: "Conflict reviewed",
    className: "bg-slate-100 text-slate-700",
    detail: "A reviewed conflict is retained even though no current Claim Fact is attached.",
  },
};

function sourceState(source: EvidenceMatrixSource) {
  if (source.document_deleted) return "Unavailable";
  return source.document_is_current ? "Current" : "Superseded";
}

function SourceCard({ source }: { source: EvidenceMatrixSource }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-slate-900">
          {source.document_name}
        </span>
        <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600">
          v{source.document_version} · {sourceState(source)}
        </span>
        {source.authoritative ? (
          <span className="rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] font-semibold text-cyan-800">
            Authoritative source
          </span>
        ) : (
          <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
            Corroborating source
          </span>
        )}
      </div>
      <p className="mt-1 text-[11px] text-slate-500">
        {source.document_type
          ? humanizeFieldLabel(source.document_type)
          : "Unclassified evidence"}
        {source.source_locator_value
          ? ` · ${source.source_locator_type ?? "source"} ${source.source_locator_value}`
          : ""}
        {source.source_verified ? " · Source verified" : " · Manual verification"}
      </p>
      {source.source_quote ? (
        <p className="mt-2 border-l-2 border-slate-300 pl-2 text-xs leading-5 text-slate-600">
          {source.source_quote}
        </p>
      ) : null}
    </div>
  );
}

export default function EvidenceMatrixPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [matrix, setMatrix] = useState<EvidenceMatrixResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([getClaim(id), getEvidenceMatrix(id)])
      .then(([claimData, matrixData]) => {
        if (!active) return;
        setClaim(claimData);
        setMatrix(matrixData);
        setError("");
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof ApiError ? reason.detail : "Evidence Matrix could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [id]);

  const attentionCount = useMemo(
    () =>
      matrix?.rows.filter((row) =>
        ["conflict_open", "source_superseded", "source_deleted", "unsupported"].includes(
          row.status,
        ),
      ).length ?? 0,
    [matrix],
  );

  if (!claim || !matrix) {
    return (
      <div className="py-20 text-center text-sm text-slate-500">
        {error || "Loading Evidence Matrix…"}
      </div>
    );
  }

  return (
    <div>
      <Link
        href={`/claims/${id}`}
        className="text-sm font-semibold text-slate-500 hover:text-slate-800"
      >
        ← Back to claim
      </Link>

      <div className="mt-5">
        <p className="eyebrow">{claim.claim_reference}</p>
        <h1 className="page-title">Evidence Matrix</h1>
        <p className="page-subtitle">
          Human-approved Claim Facts aligned with their reviewed sources, evidence versions
          and active conflicts. This is a read-only provenance view and does not decide
          causation, coverage or which conflicting source is true.
        </p>
      </div>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel p-5">
          <p className="metric-label">Approved facts</p>
          <p className="metric-value">{matrix.summary.approved_fact_count}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">Reviewed sources</p>
          <p className="metric-value">{matrix.summary.supporting_source_count}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">Open conflicts</p>
          <p className="metric-value">{matrix.summary.open_conflict_count}</p>
        </div>
        <div className="panel p-5">
          <p className="metric-label">Needs attention</p>
          <p className="metric-value">{attentionCount}</p>
        </div>
      </section>

      <section className="panel mt-6 overflow-hidden">
        <div className="border-b border-slate-200 px-6 py-5">
          <h2 className="section-title">Facts, sources and conflicts</h2>
          <p className="section-subtitle">
            Current and historical evidence remain distinguishable. Approval never transfers
            automatically when a source document is replaced.
          </p>
        </div>

        {matrix.rows.length ? (
          <div className="overflow-x-auto">
            <table className="data-table min-w-[1180px]">
              <thead>
                <tr>
                  <th className="w-[190px]">Topic</th>
                  <th className="w-[220px]">Fact</th>
                  <th className="w-[340px]">Supporting Evidence</th>
                  <th className="w-[300px]">Conflicting Evidence</th>
                  <th className="w-[170px]">Status</th>
                </tr>
              </thead>
              <tbody>
                {matrix.rows.map((row) => {
                  const meta = statusMeta[row.status];
                  return (
                    <tr key={row.row_key} className="align-top">
                      <td>
                        <p className="font-semibold text-slate-900">{row.topic}</p>
                        {row.field_path ? (
                          <p className="mt-1 text-[11px] text-slate-400">
                            {humanizeFieldLabel(row.field_path)}
                          </p>
                        ) : (
                          <p className="mt-1 text-[11px] text-slate-400">
                            Conflict-only review item
                          </p>
                        )}
                      </td>
                      <td>
                        {row.fact_id ? (
                          <>
                            <p className="break-words text-sm font-semibold text-slate-900">
                              {formatStructuredValue(row.fact_value)}
                            </p>
                            <p className="mt-2 text-[11px] text-slate-500">
                              Claim Fact v{row.fact_version}
                              {row.approved_at
                                ? ` · approved ${new Date(row.approved_at).toLocaleDateString()}`
                                : ""}
                            </p>
                          </>
                        ) : (
                          <p className="text-sm text-slate-500">
                            No authoritative Claim Fact
                          </p>
                        )}
                      </td>
                      <td>
                        {row.supporting_evidence.length ? (
                          <div className="space-y-2">
                            {row.supporting_evidence.map((source) => (
                              <SourceCard key={source.extraction_id} source={source} />
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">No reviewed source available.</p>
                        )}
                      </td>
                      <td>
                        {row.conflicting_evidence.length ? (
                          <div className="space-y-2">
                            {row.conflicting_evidence.map((conflict) => (
                              <div
                                key={conflict.id}
                                className="rounded-lg border border-red-100 bg-red-50/60 p-3"
                              >
                                <div className="flex flex-wrap items-center gap-2">
                                  <p className="text-xs font-semibold text-red-950">
                                    {conflict.topic}
                                  </p>
                                  <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold uppercase text-red-700">
                                    {humanizeFieldLabel(conflict.status)}
                                  </span>
                                </div>
                                <p className="mt-2 text-xs leading-5 text-slate-600">
                                  {conflict.description}
                                </p>
                                <div className="mt-2 space-y-1 text-[11px] text-slate-600">
                                  <p>
                                    <span className="font-semibold">A:</span>{" "}
                                    {formatStructuredValue(conflict.value_a)}
                                  </p>
                                  <p>
                                    <span className="font-semibold">B:</span>{" "}
                                    {formatStructuredValue(conflict.value_b)}
                                  </p>
                                  {conflict.difference_minutes ? (
                                    <p>
                                      <span className="font-semibold">Difference:</span>{" "}
                                      {conflict.difference_minutes} minutes
                                    </p>
                                  ) : null}
                                </div>
                                {conflict.resolution_note ? (
                                  <p className="mt-2 border-t border-red-100 pt-2 text-[11px] leading-5 text-slate-600">
                                    Human review: {conflict.resolution_note}
                                  </p>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">No active conflict linked.</p>
                        )}
                      </td>
                      <td>
                        <span
                          className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${meta.className}`}
                        >
                          {meta.label}
                        </span>
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
              No reviewed facts or conflicts are available yet.
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Approve source-linked evidence in the AI Review queue to populate the matrix.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
