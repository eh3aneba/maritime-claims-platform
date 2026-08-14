"use client";

import Link from "next/link";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";

import {
  ApiError,
  deleteClaimDocument,
  downloadClaimDocument,
  listClaimDocuments,
  runDocumentIntelligence,
  uploadClaimDocument,
} from "@/lib/api";
import type { ClaimDocument, ConfidentialityLevel, QuarantinedUpload } from "@/lib/types";

type UploadState = { name: string; progress: number; status: "uploading" | "done" | "error"; error?: string };
type DocumentIntelligenceType = Parameters<typeof runDocumentIntelligence>[2];

const documentTypes = [
  ["", "Unclassified"],
  ["claim_notification", "Claim Notification"],
  ["chief_engineer_report", "Chief Engineer Report"],
  ["engine_log", "Engine Log"],
  ["workshop_report", "Workshop Report"],
  ["policy", "H&M Policy / Wording"],
  ["running_hours_record", "Running Hours Record"],
  ["overhaul_report", "Last Overhaul Report"],
  ["pms_record", "PMS History"],
  ["maker_recommendation", "Maker Recommendation"],
  ["class_report", "Class Report / Approval"],
  ["quotation", "Quotation"],
  ["invoice", "Invoice"],
  ["final_invoice", "Final Repair Invoice"],
  ["towage_contract", "Towage Contract"],
  ["towage_invoice", "Towage Invoice"],
  ["towage_report", "Towage / Tug Report"],
  ["temporary_repair_specification", "Temporary Repair Specification"],
  ["permanent_repair_plan", "Permanent Repair Plan"],
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
  const [quarantinedUploads, setQuarantinedUploads] = useState<QuarantinedUpload[]>([]);
  const [documentType, setDocumentType] = useState("");
  const [confidentiality, setConfidentiality] = useState<ConfidentialityLevel>("confidential");
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [intelligenceState, setIntelligenceState] = useState<Record<string, string>>({});

  async function refresh() {
    try {
      const result = await listClaimDocuments(claimId);
      setDocuments(result.items);
      setQuarantinedUploads(result.quarantined_items);
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
        const uploaded = await uploadClaimDocument(
          claimId,
          file,
          { documentType: documentType || undefined, confidentiality },
          (progress) => setUploads((current) => current.map((item, i) => i === index ? { ...item, progress } : item)),
        );
        setUploads((current) => current.map((item, i) => i === index ? {
          ...item,
          progress: 100,
          status: "done",
          name: uploaded.malware_scan_status === "clean" ? `${item.name} · malware scan clean` : item.name,
        } : item));
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

  async function analyzeDocument(document: ClaimDocument) {
    const typeMap: Record<string, DocumentIntelligenceType> = {
      chief_engineer_report: "ce-report",
      engine_log: "engine-log",
      running_hours_record: "running-hours",
      pms_record: "pms-history",
      workshop_report: "workshop-report",
      quotation: "quotation",
      invoice: "invoice",
    };
    const intelligenceType = document.document_type ? typeMap[document.document_type] ?? null : null;
    if (!intelligenceType) return;
    setError("");
    setIntelligenceState((current) => ({ ...current, [document.id]: "Queueing…" }));
    try {
      const result = await runDocumentIntelligence(claimId, document.id, intelligenceType);
      setIntelligenceState((current) => ({ ...current, [document.id]: `AI ${result.status}` }));
    } catch (e) {
      const message = e instanceof ApiError ? e.detail : "Document intelligence could not be queued.";
      setIntelligenceState((current) => ({ ...current, [document.id]: "" }));
      setError(message);
    }
  }

  return (
    <section className="panel p-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <h2 className="section-title">Evidence & documents</h2>
          <p className="section-subtitle">Evidence is isolated by tenant, checked by SHA-256 and malware-scanned before processing.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
          <span className="rounded-full bg-slate-100 px-2.5 py-1">{documents.length} files</span>
          {quarantinedUploads.length ? <span className="rounded-full bg-red-50 px-2.5 py-1 text-red-700">{quarantinedUploads.length} quarantined</span> : null}
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
        <p className="mt-1 text-xs text-slate-500">PDF, JPG, PNG, DOCX or XLSX · maximum 25 MB · scanned before admission</p>
        <button type="button" onClick={() => inputRef.current?.click()} className="secondary-button mt-4">Choose files</button>
      </div>

      {uploads.length ? <div className="mt-4 space-y-2">{uploads.map((upload, index) => <div key={`${upload.name}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex items-center justify-between gap-4"><p className="truncate text-sm font-medium text-slate-700">{upload.name}</p><span className={`text-xs font-semibold ${upload.status === "error" ? "text-red-600" : upload.status === "done" ? "text-emerald-600" : "text-slate-500"}`}>{upload.status === "error" ? "Failed" : upload.status === "done" ? "Uploaded" : `${upload.progress}%`}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full transition-all ${upload.status === "error" ? "bg-red-500" : "bg-cyan-700"}`} style={{ width: `${upload.progress}%` }} /></div>{upload.error ? <p className="mt-2 text-xs text-red-600">{upload.error}</p> : null}</div>)}</div> : null}

      {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
        {loading ? <div className="p-6 text-sm text-slate-500">Loading documents…</div> : documents.length === 0 ? <div className="p-8 text-center"><p className="text-sm font-medium text-slate-700">No active evidence uploaded yet</p><p className="mt-1 text-xs text-slate-500">Start with the Chief Engineer Report, Engine Log or Workshop Report.</p></div> : <div className="overflow-x-auto"><table className="data-table min-w-[840px]"><thead><tr><th>Document</th><th>Type</th><th>Size</th><th>Integrity</th><th>Access</th><th className="text-right">Actions</th></tr></thead><tbody>{documents.map((document) => <tr key={document.id}><td><p className="font-medium text-slate-800">{document.original_filename}</p><p className="mt-1 text-xs text-slate-400">Uploaded {new Date(document.created_at).toLocaleString()}</p></td><td>{readableType(document.document_type)}</td><td>{formatBytes(document.file_size_bytes)}</td><td><span title={document.file_hash} className="font-mono text-xs text-slate-500">SHA-256 · {document.file_hash.slice(0, 10)}…</span><p className={`mt-1 text-[11px] font-semibold ${document.malware_scan_status === "clean" ? "text-emerald-700" : "text-amber-700"}`}>{document.malware_scan_status === "clean" ? "Malware scan · Clean" : "Legacy evidence · Not scanned"}</p></td><td><span className="capitalize">{document.confidentiality_level}</span></td><td><div className="flex flex-wrap justify-end gap-2">{document.processing_status === "processed" && ["chief_engineer_report", "engine_log", "running_hours_record", "pms_record", "workshop_report", "quotation", "invoice"].includes(document.document_type ?? "") ? <button onClick={() => analyzeDocument(document)} className="text-xs font-semibold text-indigo-700 hover:text-indigo-950">{intelligenceState[document.id] || (document.document_type === "engine_log" ? "Analyze log" : document.document_type === "running_hours_record" ? "Analyze hours" : document.document_type === "pms_record" ? "Analyze PMS" : "Analyze report")}</button> : null}<button onClick={() => download(document)} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">Download</button><button onClick={() => removeDocument(document)} className="text-xs font-semibold text-red-600 hover:text-red-800">Remove</button></div>{intelligenceState[document.id] ? <div className="mt-1 text-right"><Link href="/ai-review" className="text-[11px] font-semibold text-slate-500 hover:text-slate-800">Open AI review</Link></div> : null}</td></tr>)}</tbody></table></div>}
      </div>

      {quarantinedUploads.length ? <div className="mt-6 overflow-hidden rounded-xl border border-red-200 bg-red-50/40"><div className="border-b border-red-200 px-4 py-3"><h3 className="text-sm font-semibold text-red-900">Quarantined uploads</h3><p className="mt-1 text-xs text-red-700">These files are excluded from the claim record, downloads and document processing.</p></div><div className="overflow-x-auto"><table className="data-table min-w-[720px]"><thead><tr><th>Upload</th><th>Size</th><th>Scan result</th><th>Reference</th></tr></thead><tbody>{quarantinedUploads.map((upload) => <tr key={upload.id}><td><p className="font-medium text-slate-800">{upload.original_filename}</p><p className="mt-1 text-xs text-slate-500">Blocked {new Date(upload.scanned_at).toLocaleString()}</p></td><td>{formatBytes(upload.file_size_bytes)}</td><td><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${upload.status === "infected" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"}`}>{upload.status === "infected" ? `Malware detected${upload.threat_name ? ` · ${upload.threat_name}` : ""}` : "Scanner unavailable · upload held"}</span></td><td><span className="font-mono text-xs text-slate-500">{upload.id.slice(0, 8)}…</span></td></tr>)}</tbody></table></div></div> : null}
    </section>
  );
}
