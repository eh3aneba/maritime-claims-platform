"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  downloadClaimPackExport,
  generateClaimPackExport,
  getClaim,
  listClaimPackExports,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Claim, ClaimPackExport, ClaimPackFormat } from "@/lib/types";

const formatLabel: Record<ClaimPackFormat, string> = {
  pdf: "PDF",
  xlsx: "Excel",
};

export default function ClaimPackExportPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<Claim | null>(null);
  const [exports, setExports] = useState<ClaimPackExport[]>([]);
  const [acknowledged, setAcknowledged] = useState(false);
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState<ClaimPackFormat | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    try {
      const [claimRow, history] = await Promise.all([
        getClaim(id),
        listClaimPackExports(id),
      ]);
      setClaim(claimRow);
      setExports(history.items);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : "Claim-pack exports could not be loaded.",
      );
    }
  }

  useEffect(() => {
    load();
  }, [id]);

  async function createExport(exportFormat: ClaimPackFormat) {
    if (!acknowledged) {
      setError("Confirm the review-aid notice before generating a claim pack.");
      return;
    }
    setCreating(exportFormat);
    setError("");
    setNotice("");
    try {
      const created = await generateClaimPackExport(id, {
        export_format: exportFormat,
        acknowledge_review_aid: true,
        generation_note: note.trim() || null,
      });
      setExports((current) => [
        created,
        ...current.filter((item) => item.id !== created.id),
      ]);
      setNotice(
        formatLabel[exportFormat] +
          " snapshot generated. The recorded file and snapshot hashes will remain immutable.",
      );
      setNote("");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : "The controlled claim pack could not be generated.",
      );
    } finally {
      setCreating(null);
    }
  }

  async function download(item: ClaimPackExport) {
    setDownloading(item.id);
    setError("");
    try {
      await downloadClaimPackExport(id, item);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : "The claim-pack download failed.",
      );
    } finally {
      setDownloading(null);
    }
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
          Claim Pack Export
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          Generate a controlled snapshot of the reviewed claim file for internal
          review or authorized circulation. PDF and Excel use the same canonical
          snapshot.
        </p>
      </div>

      <section className="mt-7 rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h2 className="text-sm font-semibold text-amber-950">
          Review aid — not a claim decision
        </h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-amber-900">
          The pack records approved facts, source versions, open conflicts,
          missing evidence, actions and reviewed financial information at one
          point in time. It does not determine coverage, causation, liability,
          fraud, recoverability, reserve adequacy or settlement.
        </p>
        <label className="mt-4 flex items-start gap-3 text-sm font-medium text-amber-950">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-amber-400"
          />
          <span>
            I understand this export is a review aid and may contain open or
            unresolved items.
          </span>
        </label>
      </section>

      {error ? (
        <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      ) : null}

      <section className="panel mt-6 p-6">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <label>
            <span className="label">Generation note (optional)</span>
            <textarea
              rows={3}
              value={note}
              maxLength={1000}
              onChange={(event) => setNote(event.target.value)}
              className="field resize-none"
              placeholder="e.g. Prepared for internal technical review"
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              disabled={!acknowledged || creating !== null}
              onClick={() => createExport("pdf")}
              className="primary-button min-w-36 justify-center"
            >
              {creating === "pdf" ? "Generating…" : "Generate PDF"}
            </button>
            <button
              type="button"
              disabled={!acknowledged || creating !== null}
              onClick={() => createExport("xlsx")}
              className="secondary-button min-w-36 justify-center"
            >
              {creating === "xlsx" ? "Generating…" : "Generate Excel"}
            </button>
          </div>
        </div>
      </section>

      <section className="panel mt-6 p-6">
        <div>
          <h2 className="section-title">Controlled export history</h2>
          <p className="section-subtitle">
            Every row is an immutable snapshot with independent content and file
            hashes.
          </p>
        </div>

        {exports.length ? (
          <div className="mt-5 overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Format</th>
                  <th>Generated</th>
                  <th>File</th>
                  <th>Snapshot hash</th>
                  <th>File hash</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {exports.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
                        {formatLabel[item.export_format]}
                      </span>
                    </td>
                    <td>{formatDate(item.created_at)}</td>
                    <td>
                      <p className="max-w-xs truncate font-medium text-slate-800">
                        {item.filename}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {(item.file_size_bytes / 1024).toFixed(1)} KB
                      </p>
                    </td>
                    <td>
                      <code className="text-xs text-slate-500">
                        {item.snapshot_hash.slice(0, 12)}…
                      </code>
                    </td>
                    <td>
                      <code className="text-xs text-slate-500">
                        {item.file_hash.slice(0, 12)}…
                      </code>
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        disabled={downloading === item.id}
                        onClick={() => download(item)}
                        className="secondary-button"
                      >
                        {downloading === item.id ? "Downloading…" : "Download"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="mt-5 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-5 py-10 text-center text-sm text-slate-500">
            No controlled claim-pack snapshot has been generated yet.
          </div>
        )}
      </section>
    </div>
  );
}
