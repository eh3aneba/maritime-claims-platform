"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { ApiError, getClaim } from "@/lib/api";
import type { Claim } from "@/lib/types";
import { askClaimQuestion, type ClaimQaResponse, type ClaimQaSourceRef } from "@/lib/claim-qa-api";
import { downloadEvidenceSearchDocument, type EvidenceRetrievalMode } from "@/lib/evidence-search-api";

function hashLabel(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function statusTone(status: ClaimQaResponse["status"]) {
  if (status === "answered") return "border-emerald-200 bg-emerald-50 text-emerald-900";
  if (status === "conflicting_evidence") return "border-amber-200 bg-amber-50 text-amber-950";
  return "border-slate-200 bg-slate-50 text-slate-800";
}

function statusHeading(status: ClaimQaResponse["status"]) {
  if (status === "answered") return "Source-cited answer";
  if (status === "conflicting_evidence") return "Conflicting evidence";
  return "No sufficient evidence found";
}

export default function ClaimQaPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [question, setQuestion] = useState("");
  const [retrievalMode, setRetrievalMode] = useState<EvidenceRetrievalMode>("hybrid");
  const [includeSuperseded, setIncludeSuperseded] = useState(false);
  const [response, setResponse] = useState<ClaimQaResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [downloadId, setDownloadId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getClaim(id)
      .then(setClaim)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Claim could not be loaded."))
      .finally(() => setLoading(false));
  }, [id]);

  async function ask(event?: FormEvent) {
    event?.preventDefault();
    if (question.trim().length < 2) {
      setError("Enter a claim-file question with at least two characters.");
      return;
    }
    setAsking(true);
    setError("");
    try {
      const next = await askClaimQuestion(id, {
        question: question.trim(),
        retrieval_mode: retrievalMode,
        include_superseded: includeSuperseded,
        top_k: 5,
      });
      setResponse(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Claim Q&A could not be completed.");
    } finally {
      setAsking(false);
    }
  }

  async function download(source: ClaimQaSourceRef) {
    setDownloadId(source.document_id);
    setError("");
    try {
      await downloadEvidenceSearchDocument(id, source.document_id, source.document_filename);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Source document could not be downloaded.");
    } finally {
      setDownloadId(null);
    }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading Claim Q&amp;A…</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || "Claim unavailable."}</div>;

  return (
    <div className="space-y-6">
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to {claim.vessel.name}</Link>

      <div>
        <p className="eyebrow">{claim.claim_reference} · Phase 12F</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Claim Q&amp;A</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">
          Ask one claim-file question and receive an extractive answer built only from private Phase 12E evidence retrieval. Every material statement carries exact source lineage.
        </p>
      </div>

      <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm leading-6 text-cyan-950">
        <strong>Extractive/private only.</strong> This foundation does not call an external generative AI provider. It does not create ClaimFacts or decide coverage, liability, causation, recoverability, reserve, settlement, payment or legal rights. Conflicting passages remain conflicting until a human reviews them.
      </div>

      {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <form onSubmit={ask} className="panel p-6">
        <label>
          <span className="label">Ask the controlled claim file</span>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            className="field mt-2 min-h-24"
            placeholder="e.g. What evidence records the turbocharger operating hours before the casualty?"
            aria-label="Claim Q&A question"
          />
        </label>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label>
              <span className="label">Retrieval mode</span>
              <select
                value={retrievalMode}
                onChange={(event) => setRetrievalMode(event.target.value as EvidenceRetrievalMode)}
                className="field mt-2"
                aria-label="Claim Q&A retrieval mode"
              >
                <option value="lexical">Lexical · exact terms</option>
                <option value="hybrid">Private Hybrid · local semantic</option>
              </select>
            </label>
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-700">
              <input type="checkbox" checked={includeSuperseded} onChange={(event) => setIncludeSuperseded(event.target.checked)} />
              Include superseded versions
            </label>
          </div>
          <button type="submit" disabled={asking} className="primary-button whitespace-nowrap disabled:opacity-40">
            {asking ? "Reviewing evidence…" : "Ask claim file"}
          </button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {[
            "What were the turbocharger operating hours before casualty?",
            "What evidence supports recent overhaul or servicing?",
            "What reason for failure is recorded in the claim file?",
          ].map((example) => (
            <button key={example} type="button" onClick={() => setQuestion(example)} className="rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50">
              {example}
            </button>
          ))}
        </div>
      </form>

      {response ? (
        <>
          <section className={`rounded-xl border p-5 ${statusTone(response.status)}`} role="status">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
              <div>
                <p className="text-xs font-bold uppercase tracking-wide">{response.status.replaceAll("_", " ")}</p>
                <h2 className="mt-1 text-xl font-semibold">{statusHeading(response.status)}</h2>
              </div>
              <span className="rounded-full bg-white/70 px-3 py-1 text-xs font-semibold">Engine {response.answer_engine_version}</span>
            </div>
            <p className="mt-4 whitespace-pre-wrap text-sm leading-7">{response.answer}</p>
          </section>

          {response.conflicts.length ? (
            <section className="panel border-amber-200 p-6" aria-label="Claim Q&A conflicts">
              <h2 className="section-title">Conflict review required</h2>
              <div className="mt-4 space-y-3">
                {response.conflicts.map((conflict, index) => (
                  <div key={`${conflict.conflict_type}-${index}`} className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
                    <p className="font-semibold">{conflict.conflict_type.replaceAll("_", " ")}</p>
                    <p className="mt-1 leading-6">{conflict.detail}</p>
                    <p className="mt-2 break-all font-mono text-[10px] text-amber-800">Statements: {conflict.statement_hashes.map(hashLabel).join(" · ")}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {response.statements.length ? (
            <section className="space-y-4" aria-label="Claim Q&A source statements">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">Source-linked statements</h2>
                <Link href={`/claims/${id}/evidence-search`} className="secondary-button">Open Evidence Search</Link>
              </div>
              {response.statements.map((statement) => (
                <article key={statement.statement_hash} className="panel p-6">
                  <div className="flex items-center justify-between gap-4">
                    <span className="rounded-full bg-slate-950 px-2.5 py-1 text-[11px] font-bold text-white">Statement #{statement.statement_number}</span>
                    <span className="font-mono text-[10px] text-slate-400">{hashLabel(statement.statement_hash)}</span>
                  </div>
                  <blockquote className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-7 text-slate-700">{statement.text}</blockquote>
                  <div className="mt-4 space-y-3">
                    {statement.source_refs.map((source) => (
                      <div key={source.search_unit_id} className="rounded-xl border border-slate-200 p-4">
                        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                          <div>
                            <p className="font-semibold text-slate-950">{source.document_filename}</p>
                            <p className="mt-1 text-xs text-slate-500">v{source.document_version} · {source.is_current_document ? "current" : "superseded"} · {source.locator_type} {source.locator_value} · {source.confidentiality_level}</p>
                          </div>
                          <button onClick={() => void download(source)} disabled={downloadId === source.document_id} className="secondary-button disabled:opacity-40">
                            {downloadId === source.document_id ? "Downloading…" : "Download source"}
                          </button>
                        </div>
                        <details className="mt-3">
                          <summary className="cursor-pointer text-xs font-semibold text-slate-500">Exact source lineage</summary>
                          <div className="mt-3 grid gap-2 text-[10px] font-mono text-slate-500 sm:grid-cols-2">
                            <p className="break-all">document {source.document_id}</p>
                            <p className="break-all">extraction {source.extraction_id}</p>
                            <p className="break-all">segment {source.segment_id}</p>
                            <p className="break-all">unit {source.search_unit_id}</p>
                            <p className="break-all">file hash {source.source_file_hash}</p>
                            <p className="break-all">unit hash {source.search_unit_hash}</p>
                          </div>
                        </details>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          ) : null}

          {response.missing_evidence.length ? (
            <section className="panel p-6">
              <h2 className="section-title">Evidence gap</h2>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">
                {response.missing_evidence.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
          ) : null}

          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="panel p-5"><p className="metric-label">Retrieval</p><p className="mt-2 text-sm font-semibold capitalize">{response.retrieval_mode}</p><p className="mt-1 text-xs text-slate-400">{response.ranking_version}</p></div>
            <div className="panel p-5"><p className="metric-label">Question hash</p><p className="mt-2 break-all font-mono text-[10px]">{hashLabel(response.question_hash)}</p></div>
            <div className="panel p-5"><p className="metric-label">Result-set hash</p><p className="mt-2 break-all font-mono text-[10px]">{hashLabel(response.result_set_hash)}</p></div>
            <div className="panel p-5"><p className="metric-label">Answer hash</p><p className="mt-2 break-all font-mono text-[10px]">{hashLabel(response.answer_hash)}</p></div>
          </section>

          {response.semantic_used ? (
            <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs leading-5 text-emerald-900">
              <strong>Private semantic retrieval:</strong> {response.semantic_provider} · {response.semantic_model} · no external semantic provider. Authorization SHA-256 {hashLabel(response.semantic_authorization_hash)}.
            </section>
          ) : null}

          <p className="text-xs leading-5 text-slate-400">{response.disclaimer}</p>
        </>
      ) : (
        <section className="panel p-8 text-center">
          <h2 className="section-title">Ask the claim file, not the open internet</h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">The answer engine can only return evidence passages retrieved from this controlled claim. If the file does not support the question, it must say so.</p>
        </section>
      )}
    </div>
  );
}
