"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { ApiError, getClaim } from "@/lib/api";
import type { Claim } from "@/lib/types";
import {
  downloadEvidenceSearchDocument,
  searchClaimEvidence,
  type EvidenceRetrievalMode,
  type EvidenceSearchResponse,
  type EvidenceSearchResult,
} from "@/lib/evidence-search-api";

function readable(value: string | null) {
  if (!value) return "Unclassified";
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function hashLabel(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function currentTone(current: boolean) {
  return current
    ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : "bg-amber-50 text-amber-800 ring-amber-200";
}

export default function EvidenceSearchPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [query, setQuery] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [retrievalMode, setRetrievalMode] = useState<EvidenceRetrievalMode>("lexical");
  const [includeSuperseded, setIncludeSuperseded] = useState(false);
  const [exactPhrase, setExactPhrase] = useState(false);
  const [response, setResponse] = useState<EvidenceSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [downloadId, setDownloadId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialQuery = params.get("q");
    const initialType = params.get("document_type");
    if (initialQuery) setQuery(initialQuery);
    if (initialType) setDocumentType(initialType);
    if (params.get("include_superseded") === "1") setIncludeSuperseded(true);
    if (params.get("mode") === "hybrid") setRetrievalMode("hybrid");

    getClaim(id)
      .then(setClaim)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Claim could not be loaded."))
      .finally(() => setLoading(false));
  }, [id]);

  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    if (query.trim().length < 2) {
      setError("Enter at least two characters to search controlled claim evidence.");
      return;
    }
    setSearching(true);
    setError("");
    try {
      const next = await searchClaimEvidence(id, {
        query: query.trim(),
        retrieval_mode: retrievalMode,
        include_superseded: includeSuperseded,
        exact_phrase: exactPhrase,
        document_types: documentType.trim() ? [documentType.trim()] : [],
        top_k: 20,
      });
      setResponse(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Evidence search could not be completed.");
    } finally {
      setSearching(false);
    }
  }

  async function download(row: EvidenceSearchResult) {
    setDownloadId(row.document_id);
    setError("");
    try {
      await downloadEvidenceSearchDocument(id, row.document_id, row.document_filename);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Source document could not be downloaded.");
    } finally {
      setDownloadId(null);
    }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">Loading Evidence Search…</div>;
  if (!claim) return <div className="panel p-6 text-sm text-red-700">{error || "Claim unavailable."}</div>;

  return (
    <div className="space-y-6">
      <Link href={`/claims/${id}`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to {claim.vessel.name}</Link>

      <div>
        <p className="eyebrow">{claim.claim_reference} · Phase 12E</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Evidence Search</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">
          Private, claim-scoped retrieval over controlled document passages. Results preserve document version, extraction, segment locator and source hashes. Search does not create facts or answer beyond the retrieved evidence.
        </p>
      </div>

      <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm leading-6 text-cyan-950">
        <strong>Evidence discovery only.</strong> Lexical mode stays inside the claim database. Private Hybrid adds a deterministic marine-concept similarity kernel running inside the API process with no network egress. No external semantic provider is selectable, and conflicting passages remain visible rather than being resolved automatically.
      </div>

      {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <form onSubmit={runSearch} className="panel p-6">
        <label>
          <span className="label">Search controlled evidence</span>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="field flex-1"
              placeholder="e.g. turbocharger overhaul running hours"
              aria-label="Evidence search query"
            />
            <button type="submit" disabled={searching} className="primary-button whitespace-nowrap disabled:opacity-40">
              {searching ? "Searching…" : "Search evidence"}
            </button>
          </div>
        </label>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,.65fr)_auto_auto] xl:items-end">
          <label>
            <span className="label">Document type filter (optional)</span>
            <input
              value={documentType}
              onChange={(event) => setDocumentType(event.target.value)}
              className="field"
              placeholder="engine_log"
              aria-label="Document type filter"
            />
          </label>
          <label>
            <span className="label">Retrieval mode</span>
            <select
              value={retrievalMode}
              onChange={(event) => setRetrievalMode(event.target.value as EvidenceRetrievalMode)}
              className="field"
              aria-label="Evidence retrieval mode"
            >
              <option value="lexical">Lexical · exact terms</option>
              <option value="hybrid">Private Hybrid · local semantic</option>
            </select>
          </label>
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-700">
            <input type="checkbox" checked={exactPhrase} onChange={(event) => setExactPhrase(event.target.checked)} />
            Exact phrase
          </label>
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-700">
            <input type="checkbox" checked={includeSuperseded} onChange={(event) => setIncludeSuperseded(event.target.checked)} />
            Include superseded versions
          </label>
        </div>
        {retrievalMode === "hybrid" ? <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs leading-5 text-emerald-900"><strong>Private Hybrid is local-only.</strong> Provider: local_in_process · model: marine-concepts-hash-v1 · network egress: disabled. Restricted evidence remains inside the API process.</div> : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {["turbocharger", "running hours", "last serviced", "reason for failure"].map((example) => (
            <button key={example} type="button" onClick={() => setQuery(example)} className="rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50">
              {example}
            </button>
          ))}
        </div>
      </form>

      {response ? (
        <>
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <div className="panel p-5"><p className="metric-label">Results</p><p className="metric-value">{response.result_count}</p></div>
            <div className="panel p-5"><p className="metric-label">Retrieval</p><p className="mt-2 text-sm font-semibold capitalize text-slate-900">{response.retrieval_mode}</p><p className="mt-1 text-xs text-slate-400">Ranking {response.ranking_version}</p></div>
            <div className="panel p-5"><p className="metric-label">Semantic kernel</p><p className="mt-2 text-sm font-semibold text-slate-900">{response.semantic_used ? "Local only" : "Not used"}</p><p className="mt-1 text-xs text-slate-400">{response.semantic_provider ?? "lexical-only"}</p></div>
            <div className="panel p-5"><p className="metric-label">Query hash</p><p className="mt-2 break-all font-mono text-[11px] text-slate-600">{hashLabel(response.query_hash)}</p></div>
            <div className="panel p-5"><p className="metric-label">Result-set hash</p><p className="mt-2 break-all font-mono text-[11px] text-slate-600">{hashLabel(response.result_set_hash)}</p></div>
          </section>

          {response.semantic_used ? <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs leading-5 text-emerald-900"><strong>Semantic authorization:</strong> {response.semantic_provider} · {response.semantic_model} · authorization SHA-256 {hashLabel(response.semantic_authorization_hash)}. This path is local in-process and performs no external network request.</section> : null}

          {response.no_sufficient_evidence_found ? (
            <section className="panel border-dashed p-8 text-center" role="status">
              <h2 className="section-title">No sufficient evidence found</h2>
              <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">
                No controlled passage matched the current claim scope and filters. The system has not generated or inferred an answer. Try a broader evidence term or review the uploaded documents.
              </p>
              <Link href={`/claims/${id}#claim-evidence`} className="secondary-button mt-5">Review claim evidence</Link>
            </section>
          ) : (
            <section className="space-y-4" aria-label="Evidence search results">
              {response.results.map((row, index) => (
                <article key={row.search_unit_id} className="panel p-6">
                  <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-slate-950 px-2.5 py-1 text-[11px] font-bold text-white">#{index + 1}</span>
                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${currentTone(row.is_current_document)}`}>
                          {row.is_current_document ? "Current version" : "Superseded version"}
                        </span>
                        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">{row.confidentiality_level}</span>
                      </div>
                      <h2 className="mt-3 text-lg font-semibold text-slate-950">{row.document_filename}</h2>
                      <p className="mt-1 text-xs text-slate-500">{readable(row.document_type)} · v{row.document_version} · {row.locator_type} {row.locator_value}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Link href={`/claims/${id}#claim-evidence`} className="secondary-button">Open claim evidence</Link>
                      <button onClick={() => void download(row)} disabled={downloadId === row.document_id} className="secondary-button disabled:opacity-40">
                        {downloadId === row.document_id ? "Downloading…" : "Download source"}
                      </button>
                    </div>
                  </div>

                  <blockquote className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-7 text-slate-700">
                    {row.snippet}
                  </blockquote>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {row.match_reasons.map((reason) => <span key={reason} className="rounded-full bg-cyan-50 px-2.5 py-1 text-[11px] font-semibold text-cyan-800">{reason.replaceAll("_", " ")}</span>)}
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">lexical {row.lexical_score.toFixed(3)}</span>
                    {row.semantic_score !== null ? <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">local semantic {row.semantic_score.toFixed(3)}</span> : null}
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">combined {row.combined_score.toFixed(3)}</span>
                  </div>

                  <details className="mt-4 rounded-xl border border-slate-200 px-4 py-3">
                    <summary className="cursor-pointer text-xs font-semibold text-slate-600">Source lineage & hashes</summary>
                    <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-3">
                      <div><dt className="detail-label">Document ID</dt><dd className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.document_id}</dd></div>
                      <div><dt className="detail-label">Extraction ID</dt><dd className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.extraction_id}</dd></div>
                      <div><dt className="detail-label">Segment ID</dt><dd className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.segment_id}</dd></div>
                      <div><dt className="detail-label">Source file hash</dt><dd className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.source_file_hash}</dd></div>
                      <div><dt className="detail-label">Text hash</dt><dd className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.normalized_text_hash}</dd></div>
                      <div><dt className="detail-label">Search-unit hash</dt><dd className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.search_unit_hash}</dd></div>
                    </dl>
                  </details>
                </article>
              ))}
            </section>
          )}
        </>
      ) : (
        <section className="panel p-8 text-center">
          <h2 className="section-title">Search the claim file, not the open internet</h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Start with a machinery term, event, running-hours phrase or clause reference. Results are limited to this claim's controlled extracted evidence and current document versions unless you explicitly include history.
          </p>
        </section>
      )}
    </div>
  );
}
