"use client";

import Link from "next/link";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import {
  ApiError,
  deleteClaimDocument,
  downloadClaimDocument,
  getCurrentUser,
  listClaimDocuments,
  purgeQuarantinedUpload,
  queueLegacyEvidenceRescan,
  replaceClaimDocument,
  retryQuarantinedUpload,
  runDocumentIntelligence,
  uploadClaimDocument,
} from "@/lib/api";
import { evidenceT, type EvidenceKey } from "@/lib/i18n-evidence";
import type { Locale } from "@/lib/i18n";
import { formatDateTime } from "@/lib/format";
import type {
  ClaimDocument,
  ConfidentialityLevel,
  CurrentUser,
  DocumentMalwareScanStatus,
  QuarantinedUpload,
} from "@/lib/types";

type UploadState = {
  name: string;
  progress: number;
  status: "uploading" | "done" | "error";
  error?: string;
  scanClean?: boolean;
};
type DocumentIntelligenceType = Parameters<typeof runDocumentIntelligence>[2];

const documentTypes: ReadonlyArray<readonly [string, EvidenceKey]> = [
  ["", "doc.unclassified"],
  ["claim_notification", "doc.claim_notification"],
  ["chief_engineer_report", "doc.chief_engineer_report"],
  ["engine_log", "doc.engine_log"],
  ["workshop_report", "doc.workshop_report"],
  ["policy", "doc.policy"],
  ["running_hours_record", "doc.running_hours_record"],
  ["overhaul_report", "doc.overhaul_report"],
  ["pms_record", "doc.pms_record"],
  ["maker_recommendation", "doc.maker_recommendation"],
  ["class_report", "doc.class_report"],
  ["quotation", "doc.quotation"],
  ["invoice", "doc.invoice"],
  ["final_invoice", "doc.final_invoice"],
  ["towage_contract", "doc.towage_contract"],
  ["towage_invoice", "doc.towage_invoice"],
  ["towage_report", "doc.towage_report"],
  ["temporary_repair_specification", "doc.temporary_repair_specification"],
  ["permanent_repair_plan", "doc.permanent_repair_plan"],
];

const confidentialityKeys: Record<ConfidentialityLevel, EvidenceKey> = {
  internal: "conf.internal",
  confidential: "conf.confidential",
  restricted: "conf.restricted",
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function readableType(value: string | null, locale: Locale) {
  const match = documentTypes.find(([type]) => type === (value ?? ""));
  if (match) return evidenceT(locale, match[1]);
  return value ? value.replaceAll("_", " ") : evidenceT(locale, "doc.unclassified");
}

function malwareStatus(status: DocumentMalwareScanStatus, locale: Locale) {
  if (status === "clean") return { label: evidenceT(locale, "scan.clean"), className: "text-emerald-700" };
  if (status === "infected_quarantined") {
    return { label: evidenceT(locale, "scan.infected"), className: "text-red-700" };
  }
  if (status === "scan_error") {
    return { label: evidenceT(locale, "scan.error"), className: "text-amber-700" };
  }
  return { label: evidenceT(locale, "scan.legacy"), className: "text-amber-700" };
}

function evidenceAvailable(document: ClaimDocument) {
  return ["clean", "legacy_unscanned"].includes(document.malware_scan_status);
}

function intelligenceActionKey(documentType: string | null): EvidenceKey {
  if (documentType === "engine_log") return "action.analyzeLog";
  if (documentType === "running_hours_record") return "action.analyzeHours";
  if (documentType === "pms_record") return "action.analyzePms";
  return "action.analyzeReport";
}

export function ClaimDocuments({ claimId }: { claimId: string }) {
  const { locale } = useLocale();
  const ev = (key: EvidenceKey, values?: Record<string, string | number>) => evidenceT(locale, key, values);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const replacementInputRef = useRef<HTMLInputElement | null>(null);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [documents, setDocuments] = useState<ClaimDocument[]>([]);
  const [quarantinedUploads, setQuarantinedUploads] = useState<QuarantinedUpload[]>([]);
  const [documentType, setDocumentType] = useState("");
  const [confidentiality, setConfidentiality] = useState<ConfidentialityLevel>("confidential");
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [operationMessage, setOperationMessage] = useState("");
  const [operationState, setOperationState] = useState<Record<string, string>>({});
  const [intelligenceState, setIntelligenceState] = useState<Record<string, string>>({});
  const [replacementTarget, setReplacementTarget] = useState<{
    document: ClaimDocument;
    reason: string;
  } | null>(null);

  const canManageEvidence = ["admin", "claims_manager"].includes(currentUser?.role ?? "");
  const isAdmin = currentUser?.role === "admin";
  const currentDocumentCount = documents.filter((document) => document.is_current).length;
  const legacyCount = documents.filter(
    (document) => document.malware_scan_status === "legacy_unscanned",
  ).length;

  async function refresh() {
    try {
      const result = await listClaimDocuments(claimId);
      setDocuments(result.items);
      setQuarantinedUploads(result.quarantined_items);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("loadError"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [claimId]);

  useEffect(() => {
    getCurrentUser().then(setCurrentUser).catch(() => setCurrentUser(null));
  }, []);

  async function uploadFiles(files: File[]) {
    const allowed = ["pdf", "jpg", "jpeg", "png", "docx", "xlsx"];
    const validFiles = files.filter((file) =>
      allowed.includes(file.name.split(".").pop()?.toLowerCase() ?? ""),
    );
    if (validFiles.length !== files.length) {
      setError(ev("filesSkipped"));
    }
    if (!validFiles.length) return;

    setUploads(validFiles.map((file) => ({ name: file.name, progress: 0, status: "uploading" })));
    for (let index = 0; index < validFiles.length; index += 1) {
      const file = validFiles[index];
      try {
        const uploaded = await uploadClaimDocument(
          claimId,
          file,
          { documentType: documentType || undefined, confidentiality },
          (progress) => setUploads((current) =>
            current.map((item, i) => i === index ? { ...item, progress } : item),
          ),
        );
        setUploads((current) => current.map((item, i) => i === index ? {
          ...item,
          progress: 100,
          status: "done",
          scanClean: uploaded.malware_scan_status === "clean",
        } : item));
      } catch (e) {
        const message = e instanceof ApiError ? e.detail : ev("uploadFailed");
        setUploads((current) => current.map((item, i) =>
          i === index ? { ...item, status: "error", error: message } : item,
        ));
      }
    }
    await refresh();
  }

  function startReplacement(document: ClaimDocument) {
    const reason = window.prompt(ev("replace.prompt"));
    if (!reason) return;
    if (reason.trim().length < 20) {
      setError(ev("replace.reasonRequired"));
      return;
    }
    if (!window.confirm(ev("replace.confirm", { filename: document.original_filename }))) return;
    setReplacementTarget({ document, reason: reason.trim() });
    window.setTimeout(() => replacementInputRef.current?.click(), 0);
  }

  async function chooseReplacement(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    const target = replacementTarget;
    if (!file || !target) {
      setReplacementTarget(null);
      return;
    }
    setError("");
    setOperationMessage("");
    setOperationState((current) => ({
      ...current,
      [target.document.id]: ev("replace.progress", { progress: 0 }),
    }));
    try {
      const replacement = await replaceClaimDocument(
        claimId,
        target.document.id,
        file,
        target.reason,
        (progress) => setOperationState((current) => ({
          ...current,
          [target.document.id]: ev("replace.progress", { progress }),
        })),
      );
      setOperationMessage(ev("replace.success", {
        newVersion: replacement.version_number,
        oldVersion: target.document.version_number,
      }));
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("replace.failed"));
    } finally {
      setOperationState((current) => ({ ...current, [target.document.id]: "" }));
      setReplacementTarget(null);
    }
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    void uploadFiles(files);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void uploadFiles(Array.from(event.dataTransfer.files));
  }

  async function queueLegacyRescan() {
    const count = Math.min(legacyCount, 25);
    if (!window.confirm(ev("rescan.confirm", { count }))) return;
    setError("");
    setOperationMessage("");
    setOperationState((current) => ({ ...current, rescan: ev("queueing") }));
    try {
      const result = await queueLegacyEvidenceRescan(claimId, count);
      setOperationMessage(ev("rescan.success", { count: result.queued_count }));
      window.setTimeout(() => void refresh(), 2500);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("rescan.failed"));
    } finally {
      setOperationState((current) => ({ ...current, rescan: "" }));
    }
  }

  async function retryQuarantine(upload: QuarantinedUpload) {
    setError("");
    setOperationMessage("");
    setOperationState((current) => ({ ...current, [upload.id]: ev("quarantine.retrying") }));
    try {
      const result = await retryQuarantinedUpload(claimId, upload.id);
      if (result.status === "released") {
        setOperationMessage(ev("quarantine.retryReleased"));
      } else if (result.status === "infected") {
        setOperationMessage(ev("quarantine.retryInfected"));
      } else {
        setOperationMessage(ev("quarantine.retryUnavailable"));
      }
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("quarantine.retryFailed"));
    } finally {
      setOperationState((current) => ({ ...current, [upload.id]: "" }));
    }
  }

  async function purgeQuarantine(upload: QuarantinedUpload) {
    const reason = window.prompt(ev("purge.prompt"));
    if (!reason) return;
    if (reason.trim().length < 20) {
      setError(ev("purge.reasonRequired"));
      return;
    }
    if (!window.confirm(ev("purge.confirm", { filename: upload.original_filename }))) return;
    setError("");
    setOperationMessage("");
    setOperationState((current) => ({ ...current, [upload.id]: ev("purge.progress") }));
    try {
      await purgeQuarantinedUpload(claimId, upload.id, reason.trim());
      setOperationMessage(ev("purge.success"));
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("purge.failed"));
    } finally {
      setOperationState((current) => ({ ...current, [upload.id]: "" }));
    }
  }

  async function removeDocument(document: ClaimDocument) {
    if (!window.confirm(ev("remove.confirm", { filename: document.original_filename }))) return;
    setError("");
    try {
      await deleteClaimDocument(claimId, document.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("remove.failed"));
    }
  }

  async function download(document: ClaimDocument) {
    setError("");
    try {
      await downloadClaimDocument(claimId, document);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : ev("download.failed"));
    }
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
    setIntelligenceState((current) => ({ ...current, [document.id]: ev("ai.queueing") }));
    try {
      const result = await runDocumentIntelligence(claimId, document.id, intelligenceType);
      setIntelligenceState((current) => ({ ...current, [document.id]: ev("ai.status", { status: result.status }) }));
    } catch (e) {
      setIntelligenceState((current) => ({ ...current, [document.id]: "" }));
      setError(e instanceof ApiError ? e.detail : ev("ai.failed"));
    }
  }

  return (
    <section className="panel p-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <h2 className="section-title">{ev("title")}</h2>
          <p className="section-subtitle">{ev("subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500">
          <span className="rounded-full bg-slate-100 px-2.5 py-1">{ev("summary.currentVersions", { current: currentDocumentCount, versions: documents.length })}</span>
          {quarantinedUploads.length ? <span className="rounded-full bg-red-50 px-2.5 py-1 text-red-700">{ev("summary.quarantined", { count: quarantinedUploads.length })}</span> : null}
          {canManageEvidence && legacyCount ? <button type="button" onClick={() => void queueLegacyRescan()} className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-800 hover:bg-amber-200">{operationState.rescan || ev("summary.rescanLegacy", { count: legacyCount })}</button> : null}
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">{ev("summary.securityActive")}</span>
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-[1fr_200px]">
        <label><span className="label">{ev("documentType")}</span><select value={documentType} onChange={(event) => setDocumentType(event.target.value)} className="field">{documentTypes.map(([value, key]) => <option value={value} key={value}>{ev(key)}</option>)}</select></label>
        <label><span className="label">{ev("confidentiality")}</span><select value={confidentiality} onChange={(event) => setConfidentiality(event.target.value as ConfidentialityLevel)} className="field"><option value="internal">{ev("conf.internal")}</option><option value="confidential">{ev("conf.confidential")}</option><option value="restricted">{ev("conf.restricted")}</option></select></label>
      </div>

      <input ref={inputRef} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx" className="hidden" onChange={chooseFiles} />
      <input ref={replacementInputRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx" className="hidden" onChange={chooseReplacement} />
      <div onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className={`mt-4 rounded-xl border-2 border-dashed px-5 py-8 text-center transition ${dragging ? "border-cyan-600 bg-cyan-50" : "border-slate-300 bg-slate-50"}`}>
        <p className="text-sm font-semibold text-slate-800">{ev("drop.title")}</p>
        <p className="mt-1 text-xs text-slate-500">{ev("drop.help")}</p>
        <button type="button" onClick={() => inputRef.current?.click()} className="secondary-button mt-4">{ev("chooseFiles")}</button>
      </div>

      {uploads.length ? <div className="mt-4 space-y-2">{uploads.map((upload, index) => <div key={`${upload.name}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex items-center justify-between gap-4"><p className="truncate text-sm font-medium text-slate-700" dir="ltr">{upload.name}</p><span className={`text-xs font-semibold ${upload.status === "error" ? "text-red-600" : upload.status === "done" ? "text-emerald-600" : "text-slate-500"}`}>{upload.status === "error" ? ev("upload.failed") : upload.status === "done" ? ev("upload.uploaded") : `${upload.progress}%`}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full transition-all ${upload.status === "error" ? "bg-red-500" : "bg-cyan-700"}`} style={{ width: `${upload.progress}%` }} /></div>{upload.scanClean ? <p className="mt-2 text-xs font-semibold text-emerald-700">{ev("scan.clean")}</p> : null}{upload.error ? <p className="mt-2 text-xs text-red-600">{upload.error}</p> : null}</div>)}</div> : null}
      {operationMessage ? <div className="mt-4 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-800">{operationMessage}</div> : null}
      {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
        {loading ? <div className="p-6 text-sm text-slate-500">{ev("loading")}</div> : documents.length === 0 ? <div className="p-8 text-center"><p className="text-sm font-medium text-slate-700">{ev("empty.title")}</p><p className="mt-1 text-xs text-slate-500">{ev("empty.help")}</p></div> : <div className="overflow-x-auto"><table className="data-table min-w-[840px]"><thead><tr><th>{ev("table.document")}</th><th>{ev("table.type")}</th><th>{ev("table.size")}</th><th>{ev("table.integrity")}</th><th>{ev("table.access")}</th><th className="text-end">{ev("table.actions")}</th></tr></thead><tbody>{documents.map((document) => { const scan = malwareStatus(document.malware_scan_status, locale); const available = evidenceAvailable(document); return <tr key={document.id} className={document.is_current ? "" : "bg-slate-50/70"}><td><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-800" dir="ltr">{document.original_filename}</p><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${document.is_current ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-600"}`}><span dir="ltr">v{document.version_number}</span> · {document.is_current ? ev("version.current") : ev("version.superseded")}</span></div><p className="mt-1 text-xs text-slate-400">{ev("uploadedAt", { date: "" }).trim()} <span dir="ltr">{formatDateTime(document.created_at, locale)}</span></p>{document.replacement_reason ? <p className="mt-1 max-w-md text-xs text-slate-500" dir="auto">{ev("replacementReason", { reason: document.replacement_reason })}</p> : null}</td><td>{readableType(document.document_type, locale)}</td><td dir="ltr">{formatBytes(document.file_size_bytes)}</td><td><span title={document.file_hash} className="font-mono text-xs text-slate-500" dir="ltr">SHA-256 · {document.file_hash.slice(0, 10)}…</span><p className={`mt-1 text-[11px] font-semibold ${scan.className}`}>{scan.label}</p></td><td>{ev(confidentialityKeys[document.confidentiality_level])}</td><td>{available ? <><div className="flex flex-wrap justify-end gap-2">{document.processing_status === "processed" && ["chief_engineer_report", "engine_log", "running_hours_record", "pms_record", "workshop_report", "quotation", "invoice"].includes(document.document_type ?? "") ? <button onClick={() => void analyzeDocument(document)} className="text-xs font-semibold text-indigo-700 hover:text-indigo-950">{intelligenceState[document.id] || ev(intelligenceActionKey(document.document_type))}</button> : null}<button onClick={() => void download(document)} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">{ev("action.download")}</button>{document.is_current ? <button onClick={() => startReplacement(document)} className="text-xs font-semibold text-indigo-700 hover:text-indigo-950">{operationState[document.id] || ev("action.replace")}</button> : null}{document.is_current ? <button onClick={() => void removeDocument(document)} className="text-xs font-semibold text-red-600 hover:text-red-800">{ev("action.remove")}</button> : null}</div>{intelligenceState[document.id] ? <div className="mt-1 text-end"><Link href="/ai-review" className="text-[11px] font-semibold text-slate-500 hover:text-slate-800">{ev("action.openAiReview")}</Link></div> : null}</> : <p className="text-end text-xs font-semibold text-red-700">{ev("action.blocked")}</p>}</td></tr>; })}</tbody></table></div>}
      </div>

      {quarantinedUploads.length ? <div className="mt-6 overflow-hidden rounded-xl border border-red-200 bg-red-50/40"><div className="border-b border-red-200 px-4 py-3"><h3 className="text-sm font-semibold text-red-900">{ev("quarantine.title")}</h3><p className="mt-1 text-xs text-red-700">{ev("quarantine.help")}</p></div><div className="overflow-x-auto"><table className="data-table min-w-[820px]"><thead><tr><th>{ev("quarantine.table.upload")}</th><th>{ev("quarantine.table.size")}</th><th>{ev("quarantine.table.scan")}</th><th>{ev("quarantine.table.reference")}</th><th className="text-end">{ev("quarantine.table.actions")}</th></tr></thead><tbody>{quarantinedUploads.map((upload) => <tr key={upload.id}><td><p className="font-medium text-slate-800" dir="ltr">{upload.original_filename}</p><p className="mt-1 text-xs text-slate-500">{ev("quarantine.blockedAt", { date: "" }).trim()} <span dir="ltr">{formatDateTime(upload.scanned_at, locale)}</span></p></td><td dir="ltr">{formatBytes(upload.file_size_bytes)}</td><td><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${upload.status === "infected" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"}`}>{upload.status === "infected" ? <>{ev("quarantine.malwareDetected")}{upload.threat_name ? <span dir="ltr"> · {upload.threat_name}</span> : null}</> : ev("quarantine.scannerUnavailable", { count: upload.retry_count })}</span></td><td><span className="font-mono text-xs text-slate-500" dir="ltr">{upload.id.slice(0, 8)}…</span></td><td><div className="flex flex-wrap justify-end gap-2">{canManageEvidence && upload.status === "scan_error" ? <button type="button" onClick={() => void retryQuarantine(upload)} className="text-xs font-semibold text-cyan-800 hover:text-cyan-950">{operationState[upload.id] || ev("quarantine.retryScan")}</button> : null}{isAdmin ? <button type="button" onClick={() => void purgeQuarantine(upload)} className="text-xs font-semibold text-red-700 hover:text-red-950">{ev("quarantine.purgeBytes")}</button> : null}{!canManageEvidence ? <span className="text-xs text-slate-500">{ev("quarantine.managerApproval")}</span> : null}</div></td></tr>)}</tbody></table></div></div> : null}
    </section>
  );
}
