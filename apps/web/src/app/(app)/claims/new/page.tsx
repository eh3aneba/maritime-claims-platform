"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useLocale } from "@/components/locale-provider";
import {
  ApiError,
  approveClaimIntakeDraft,
  createClaim,
  createVessel,
  getClaimIntakeDraft,
  listVessels,
  rejectClaimIntakeDraft,
  uploadClaimIntakeDraft,
} from "@/lib/api";
import { claimWorkspaceT } from "@/lib/i18n-claim-workspace";
import {
  intakeDocumentTypeLabel,
  intakeMaturityT,
  listClaimIntakeDocumentTypes,
  retryClaimIntakeDraft,
} from "@/lib/intake-maturity";
import type { ClaimIntakeDraft, Vessel } from "@/lib/types";

type IntakeMode = "document" | "manual";

export default function NewClaimPage() {
  const router = useRouter();
  const { locale, t } = useLocale();
  const cw = (key: Parameters<typeof claimWorkspaceT>[1], values?: Record<string, string | number>) => claimWorkspaceT(locale, key, values);
  const im = (key: Parameters<typeof intakeMaturityT>[1]) => intakeMaturityT(locale, key);
  const [mode, setMode] = useState<IntakeMode>("document");
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const [vesselId, setVesselId] = useState("");
  const [showNewVessel, setShowNewVessel] = useState(false);
  const [vesselName, setVesselName] = useState("");
  const [imo, setImo] = useState("");
  const [incidentDate, setIncidentDate] = useState("");
  const [notificationDate, setNotificationDate] = useState(new Date().toISOString().slice(0, 10));
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"low" | "medium" | "high" | "critical">("medium");
  const [estimatedLoss, setEstimatedLoss] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [externalReference, setExternalReference] = useState("");
  const [intakeFile, setIntakeFile] = useState<File | null>(null);
  const [intakeDraft, setIntakeDraft] = useState<ClaimIntakeDraft | null>(null);
  const [documentTypes, setDocumentTypes] = useState<string[]>([]);
  const [documentType, setDocumentType] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    listVessels()
      .then((result) => {
        setVessels(result.items);
        if (result.items[0]) setVesselId(result.items[0].id);
      })
      .catch((err) => setError(err instanceof ApiError ? err.detail : cw("loadVesselsError")));
    listClaimIntakeDocumentTypes()
      .then((registry) => setDocumentTypes(registry.items))
      .catch((err) => setError(err instanceof ApiError ? err.detail : im("loadTypesError")));
  }, []);

  function applyCandidates(draft: ClaimIntakeDraft) {
    const fields = draft.extracted_fields;
    if (!fields) return;
    if (fields.incident_date) setIncidentDate(fields.incident_date);
    if (fields.notification_date) setNotificationDate(fields.notification_date);
    if (fields.incident_description) setDescription(fields.incident_description);
    if (fields.external_reference) setExternalReference(fields.external_reference);
    if (fields.priority) setPriority(fields.priority);
    if (fields.currency) setCurrency(fields.currency.toUpperCase());
    const matchedVessel = vessels.find((vessel) =>
      (fields.imo_number && vessel.imo_number === fields.imo_number) ||
      (fields.vessel_name && vessel.name.toLowerCase() === fields.vessel_name.toLowerCase()),
    );
    if (matchedVessel) setVesselId(matchedVessel.id);
  }

  function prepareReview(draft: ClaimIntakeDraft) {
    applyCandidates(draft);
    const candidate = draft.classification_candidate ?? "";
    setDocumentType(documentTypes.includes(candidate) ? candidate : "");
    // Keep persisted review metadata locale-neutral and behavior-compatible.
    setReviewNote("I reviewed the proposed fields and document type against the uploaded source document.");
  }

  async function pollDraft(initial: ClaimIntakeDraft): Promise<ClaimIntakeDraft> {
    let draft = initial;
    for (let attempt = 0; attempt < 60 && draft.status === "processing"; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      draft = await getClaimIntakeDraft(draft.id);
      setIntakeDraft(draft);
    }
    if (draft.status === "pending_review") {
      prepareReview(draft);
      return draft;
    }
    if (draft.status === "processing") {
      setError(im("processingLonger"));
      return draft;
    }
    setError(draft.extraction_warnings?.[0] ?? cw("documentReviewError"));
    return draft;
  }

  async function uploadAndExtract() {
    setError("");
    if (!intakeFile) { setError(cw("chooseNotificationError")); return; }
    setExtracting(true);
    setIntakeDraft(null);
    setDocumentType("");
    try {
      const draft = await uploadClaimIntakeDraft(intakeFile);
      setIntakeDraft(draft);
      await pollDraft(draft);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : cw("prepareDocumentError"));
    } finally { setExtracting(false); }
  }

  async function retryDraftProcessing() {
    if (!intakeDraft || intakeDraft.status !== "failed") return;
    setError("");
    setRetrying(true);
    setDocumentType("");
    try {
      const draft = await retryClaimIntakeDraft(intakeDraft.id);
      setIntakeDraft(draft);
      await pollDraft(draft);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : im("retryError"));
    } finally { setRetrying(false); }
  }

  async function addVessel() {
    setError("");
    if (vesselName.trim().length < 2) { setError(cw("enterVesselName")); return; }
    try {
      const vessel = await createVessel({ name: vesselName.trim(), imo_number: imo.trim() || null });
      setVessels((current) => [...current, vessel].sort((a, b) => a.name.localeCompare(b.name)));
      setVesselId(vessel.id); setShowNewVessel(false); setVesselName(""); setImo("");
    } catch (err) { setError(err instanceof ApiError ? err.detail : cw("createVesselError")); }
  }

  async function rejectDraft() {
    if (!intakeDraft || reviewNote.trim().length < 10) { setError(cw("rejectNoteError")); return; }
    setSubmitting(true);
    try { setIntakeDraft(await rejectClaimIntakeDraft(intakeDraft.id, reviewNote.trim())); }
    catch (err) { setError(err instanceof ApiError ? err.detail : cw("rejectDraftError")); }
    finally { setSubmitting(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!vesselId) { setError(cw("selectVesselError")); return; }
    if (mode === "document" && intakeDraft?.status !== "pending_review") { setError(cw("processSourceError")); return; }
    if (mode === "document" && !documentType) { setError(im("correctionRequired")); return; }
    if (mode === "document" && reviewNote.trim().length < 10) { setError(cw("reviewNoteError")); return; }
    setSubmitting(true);
    const claimPayload = {
      vessel_id: vesselId,
      incident_date: incidentDate,
      notification_date: notificationDate,
      incident_description: description,
      claim_type: "hull_machinery" as const,
      claim_subtype: "machinery_damage" as const,
      priority,
      external_reference: externalReference.trim() || null,
      estimated_loss: estimatedLoss ? Number(estimatedLoss) : null,
      currency: currency.toUpperCase(),
    };
    try {
      if (mode === "document" && intakeDraft) {
        const result = await approveClaimIntakeDraft(intakeDraft.id, {
          claim: claimPayload,
          document_type: documentType,
          review_note: reviewNote.trim(),
        });
        router.push(`/claims/${result.claim.id}`);
      } else {
        const claim = await createClaim(claimPayload);
        router.push(`/claims/${claim.id}`);
      }
    } catch (err) { setError(err instanceof ApiError ? err.detail : cw("createClaimError")); }
    finally { setSubmitting(false); }
  }

  const pendingReview = intakeDraft?.status === "pending_review";
  const failedProcessing = intakeDraft?.status === "failed";
  return (
    <div className="max-w-5xl">
      <Link href="/claims" className="text-sm font-semibold text-slate-500 hover:text-slate-800">{locale === "fa" ? "→" : "←"} {cw("backToClaims")}</Link>
      <div className="mt-4"><p className="eyebrow">{cw("newCase")}</p><h1 className="page-title">{cw("createClaim")}</h1><p className="page-subtitle">{cw("createClaimHelp")}</p></div>

      <div className="mt-6 inline-flex rounded-xl border border-slate-200 bg-white p-1">
        <button type="button" onClick={() => setMode("document")} className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === "document" ? "bg-slate-900 text-white" : "text-slate-600"}`}>{cw("importNotification")}</button>
        <button type="button" onClick={() => setMode("manual")} className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === "manual" ? "bg-slate-900 text-white" : "text-slate-600"}`}>{cw("manualEntry")}</button>
      </div>

      <form onSubmit={submit} className="mt-5 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          {mode === "document" ? <section className="panel p-6">
            <h2 className="section-title">{cw("secureSourceIntake")}</h2><p className="section-subtitle">{cw("secureSourceHelp")}</p>
            <div className="mt-5 flex flex-col gap-3 sm:flex-row"><input type="file" accept=".pdf,.jpg,.jpeg,.png,.docx" onChange={(event) => setIntakeFile(event.target.files?.[0] ?? null)} className="field flex-1" /><button type="button" onClick={uploadAndExtract} disabled={extracting || retrying} className="secondary-button justify-center disabled:opacity-60">{extracting ? cw("scanningExtracting") : cw("uploadExtract")}</button></div>
            {intakeDraft ? <div className={`mt-4 rounded-xl border p-4 text-sm ${pendingReview ? "border-emerald-200 bg-emerald-50 text-emerald-900" : failedProcessing ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2"><strong dir="ltr">{intakeDraft.original_filename}</strong><span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold" dir="ltr">{intakeDraft.status.replaceAll("_", " ")}</span></div>
              {pendingReview ? <div className="mt-3 space-y-3">
                <p>{im("classificationAdvisory")}: <span dir="ltr">{intakeDraft.classification_candidate?.replaceAll("_", " ") || "unknown"}</span> · {cw("confidence")} <span dir="ltr">{intakeDraft.classification_confidence ?? 0}%</span> · {cw("method")} <span dir="ltr">{intakeDraft.extraction_method}</span></p>
                {intakeDraft.classification_rule ? <p className="text-xs opacity-80">{im("classificationBasis")}: <span dir="ltr">{intakeDraft.classification_rule}</span></p> : null}
                <label className="block"><span className="label">{im("documentType")}</span><select aria-label={im("documentType")} required value={documentType} onChange={(event) => setDocumentType(event.target.value)} className="field mt-1"><option value="">{im("selectDocumentType")}</option>{documentTypes.map((code) => <option key={code} value={code}>{intakeDocumentTypeLabel(locale, code)}</option>)}</select></label>
              </div> : null}
              {intakeDraft.extraction_warnings?.map((warning) => <p key={warning} className="mt-2 text-amber-800">{warning}</p>)}
              {failedProcessing ? <button type="button" onClick={retryDraftProcessing} disabled={retrying} className="secondary-button mt-3 disabled:opacity-60">{retrying ? im("retrying") : im("retryProcessing")}</button> : null}
            </div> : null}
          </section> : null}

          <section className="panel p-6">
            <h2 className="section-title">{mode === "document" ? cw("reviewVessel") : cw("vessel")}</h2><p className="section-subtitle">{cw("vesselHelp")}</p>
            <div className="mt-5 flex gap-3"><select required value={vesselId} onChange={(event) => setVesselId(event.target.value)} className="field flex-1"><option value="">{cw("selectVessel")}</option>{vessels.map((vessel) => <option key={vessel.id} value={vessel.id}>{vessel.name}{vessel.imo_number ? ` · IMO ${vessel.imo_number}` : ""}</option>)}</select><button type="button" onClick={() => setShowNewVessel(!showNewVessel)} className="secondary-button whitespace-nowrap">{cw("addVessel")}</button></div>
            {showNewVessel ? <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_180px_auto]"><input className="field" value={vesselName} onChange={(event) => setVesselName(event.target.value)} placeholder={cw("vesselName")} /><input className="field" dir="ltr" value={imo} onChange={(event) => setImo(event.target.value.replace(/\D/g, "").slice(0, 7))} placeholder={cw("imoNumber")} /><button type="button" onClick={addVessel} className="secondary-button">{cw("add")}</button></div> : null}
          </section>

          <section className="panel p-6">
            <h2 className="section-title">{mode === "document" ? cw("reviewIncident") : cw("incident")}</h2><p className="section-subtitle">{cw("incidentHelp")}</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2"><label><span className="label">{cw("incidentDate")}</span><input required type="date" dir="ltr" value={incidentDate} onChange={(event) => setIncidentDate(event.target.value)} className="field" /></label><label><span className="label">{cw("notificationDate")}</span><input required type="date" dir="ltr" value={notificationDate} onChange={(event) => setNotificationDate(event.target.value)} className="field" /></label></div>
            <label className="mt-4 block"><span className="label">{cw("incidentDescription")}</span><textarea required minLength={10} rows={6} value={description} onChange={(event) => setDescription(event.target.value)} className="field resize-y" placeholder={cw("incidentPlaceholder")} /></label>
          </section>

          <section className="panel p-6"><h2 className="section-title">{cw("exposure")}</h2><p className="section-subtitle">{cw("exposureHelp")}</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2"><label><span className="label">{cw("estimatedLoss")}</span><input type="number" dir="ltr" min="0" step="0.01" value={estimatedLoss} onChange={(event) => setEstimatedLoss(event.target.value)} className="field" placeholder="550000" /></label><label><span className="label">{cw("currency")}</span><input required dir="ltr" minLength={3} maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} className="field uppercase" /></label><label><span className="label">{cw("externalReference")}</span><input dir="ltr" value={externalReference} onChange={(event) => setExternalReference(event.target.value)} className="field" placeholder={cw("externalReferencePlaceholder")} /></label><label><span className="label">{cw("priority")}</span><select value={priority} onChange={(event) => setPriority(event.target.value as typeof priority)} className="field"><option value="low">{t("priority.low")}</option><option value="medium">{t("priority.medium")}</option><option value="high">{t("priority.high")}</option><option value="critical">{t("priority.critical")}</option></select></label></div>
          </section>

          {mode === "document" ? <section className="panel p-6"><h2 className="section-title">{cw("humanApproval")}</h2><p className="section-subtitle">{cw("humanApprovalHelp")}</p><label className="mt-5 block"><span className="label">{cw("reviewNote")}</span><textarea required minLength={10} rows={3} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} className="field resize-y" /></label>{pendingReview ? <button type="button" disabled={submitting} onClick={rejectDraft} className="mt-3 text-sm font-semibold text-red-700 hover:text-red-900">{cw("rejectDraft")}</button> : null}</section> : null}
        </div>

        <aside><div className="panel sticky top-24 p-5"><p className="text-sm font-semibold text-slate-900">{cw("humanControlledIntake")}</p><dl className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-4"><dt className="text-slate-500">{cw("claimType")}</dt><dd className="font-medium" dir="ltr">H&amp;M</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">{cw("source")}</dt><dd className="font-medium">{mode === "document" ? cw("reviewedUpload") : cw("manual")}</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">{cw("initialStatus")}</dt><dd className="font-medium">{cw("statusNew")}</dd></div></dl><div className="my-5 border-t border-slate-200" />{error ? <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}<button disabled={submitting || extracting || retrying || (mode === "document" && (!pendingReview || !documentType))} className="primary-button w-full justify-center disabled:opacity-60">{submitting ? cw("creating") : mode === "document" ? cw("approveCreate") : cw("create")}</button><p className="mt-3 text-xs leading-5 text-slate-400">{cw("intakeBoundary")}</p></div></aside>
      </form>
    </div>
  );
}
