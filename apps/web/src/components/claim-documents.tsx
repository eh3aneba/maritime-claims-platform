"use client";

import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";

import {
  ApiError,
  deleteClaimDocument,
  downloadClaimDocument,
  listClaimDocuments,
  uploadClaimDocument,
} from "@/lib/api";
import type { ClaimDocument, ConfidentialityLevel } from "@/lib/types";

type UploadState = { name: string; progress: number; status: "uploading" | "done" | "error"; error?: string };

const documentTypes = [
  ["", "Unclassified"],
  ["claim_notification", "Claim Notification"],
  ["chief_engineer_report", "Chief Engineer Report"],
  ["engine_log", "Engine Log"],
  ["workshop_report", "Workshop Report"],
  ["quotation", "Quotation"],
  ["invoice", "Invoice"],
] as const;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function readableType(value: string | null) {
  if (!value) return "Unclassified";
  return value.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

export function ClaimDocuments({ claimId }: { claimId: string }) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [documents, setDocuments] = useState<ClaimDocument[]>([]);
  const [documentType, setDocumentType] = useState("");
  const [confidentiality, setConfidentiality] = useState<ConfidentialityLevel>("confidential");
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      const result = await listClaimDocuments(claimId);
      setDocuments(result.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Documents could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, [claimId]);

  async function uploadFiles(files: File[]) {
    const allowed = ["pdf", "jpg", "jpeg", "png", "docx", "xlsx"];
    const validFiles = files.filter((file) => allowed.includes(file.name.split(".").pop()?.toLowerCase() ?? ""));
    if (validFiles.length !== files.length) setError("Some files were skipped. Allowed: PDF, JPG, PNG, DOCX, XLSX.");
    if (!validFiles.length) return;

    const initial = validFiles.map((file) => ({ name: file.name, progress: 0, status: "uploading" as const }));
    setUploads(initial);

    for (let index = 0; index < validFiles.length; index += 1) {
      const file = validFiles[index];
      try {
        await uploadClaimDocument(
          claimId,
          file,
          { documentType: documentType || undefined, confidentiality },
          (progress) => setUploads((current) => current.map((item, i) => i === index ? { ...item, progress } : item)),
        );
        setUploads((current) => current.map((item, i) => i === index ? { ...item, progress: 100, status: "done" } : item));
      } catch (e) {
        const message = e instanceof ApiError ? e.detail : "Upload failed.";
        setUploads((current) => current.map((item, i) => i === index ? { ...item, status: "error", error: message } : item));
      }
    }
    await refresh();
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    uploadFiles(files);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    uploadFiles(Array.from(event.dataTransfer.files));
  }

  async function removeDocument(document: ClaimDocument) {
    if (!window.confirm(`Remove ${document.original_filename} from the active claim file? The evidence bytes will be retained for audit.`)) return;
    setError("");
    try {
      await deleteClaimDocument(claimId, document.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Document could not be removed.");
    }
  }

  async function download(document: ClaimDocument) {
    setError("");
    try { await downloadClaimDocument(claimId, document); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Document could not be downloaded."); }
  }

  return (
    <section className="panel p-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <h2 className="section-title">Evidence & documents</h2>
          <p className="section-subtitle">Secure claim evidence with checksum-based duplicate detection and tenant-isolated storage.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
          <span className="rounded-full bg-slate-100 px-2.5 py-1">{documents.length} files</span>
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">Evidence foundation active</span>
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-[1fr_200px]">
        <label><span className="label">Document type</span><select value={documentType} onChange={(e) => setDocumentType(e.target.value)} className="field">{documentTypes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label><span className="label">Confidentiality</span><select value={confidentiality} onChange={(e) => setConfidentiality(e.target.value as ConfidentialityLevel)} className="field"><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option></select></label>
      </div>

      <input ref={inputRef} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx" className="hidden" onChange={chooseFiles} />
      <div
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`mt-4 rounded-xl border-2 border-dashed px-5 py-8 text-center transition ${dragging ? "border-cyan-600 bg-cyan-50" : "border-slate-300 bg-slate-50"}`}
      >
        <p className="text-sm font-semibold text-slate-800">Drop claim evidence here</p>
        <p className="mt-1 text-xs text-slate-500">PDF, JPG, PNG, DOCX or XLSX · maximum 25 MB per file</p>
        <button type="button" onClick={() => inputRef.current?.click()} className="secondary-button mt-4">Choose files</button>
      </div>

      {uploads.length ? <div className="mt-4 space-y-2">{uploads.map((upload, index) => <div key={`${upload.name}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex items-center justify-between gap-4"><p className="truncate text-sm font-medium text-slate-700">{upload.name}</p><span className={`text-xs font-semibold ${upload.status === "error" ? "text-red-600" : upload.status === "done" ? "text-emerald-600" : "text-slate-500"}`}>{upload.status === "error" ? "Failed" : upload.status === "done" ? "Uploaded" : `${upload.progress}%`}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full transition-all ${upload.status === "error" ? "bg-red-500" : "bg-cyan-700"}`} style={{ width: `${upload.progress}%` }} /></div>{upload.error ? <p className="mt-2 text-xs text-red-600">{upload.error}</p> : null}</div>)}</div> : null}

      {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
        {loading ? <div className="p-6 text-sm text-slate-500">Loading documents…</div> : documents.length === 0 ? <div className="p-8 text-center"><p className="text-sm font-medium text-slate-700">No evidence uploaded yet</p><p className="mt-1 text-xs text-slate-500">Start with the Chief Engineer Report, Engine Log or Workshop Report.</p></div> : <div className="overflow-x-auto"><table className="data-table min-w-[760px]"><thead><tr><th>Document</th><th>Type</th><th>Size</th><th>Integrity</th><th>Access</th><th className="text-right">Actions</th></tr></thead><tbody>{documents.map((document) => <tr key={document.id}><td><p className="font-medium text-slate-800">{document.original_filename}</p><p className="mt-1 text-xs text-slate-400">Uploaded {new Date(document.created_at).toLocaleString()}</p></td><td>{readableType(document.document_type)}</td><td>{formatBytes(document.file_size_bytes)}</td><td><span title={document.file_hash} className="font-mono text-xs text-slate-500">SHA-256 · {document.file_hash.slice(0, 10)}…</span></td><td><span className="capitalize">{document.confidentiality_level}</span></td><td><div className="flex justify-end gap-2"><button onClick={() => download(document)} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">Download</button><button onClick={() => removeDocument(document)} className="text-xs font-semibold text-red-600 hover:text-red-800">Remove</button></div></td></tr>)}</tbody></table></div>}
      </div>
    </section>
  );
}
