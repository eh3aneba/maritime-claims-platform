"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

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
import type { ClaimIntakeDraft, Vessel } from "@/lib/types";

type IntakeMode = "document" | "manual";

export default function NewClaimPage() {
  const router = useRouter();
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
  const [reviewNote, setReviewNote] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [extracting, setExtracting] = useState(false);

  useEffect(() => {
    listVessels()
      .then((result) => {
        setVessels(result.items);
        if (result.items[0]) setVesselId(result.items[0].id);
      })
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Could not load vessels."));
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
    const matchedVessel = vessels.find(
      (vessel) =>
        (fields.imo_number && vessel.imo_number === fields.imo_number) ||
        (fields.vessel_name && vessel.name.toLowerCase() === fields.vessel_name.toLowerCase()),
    );
    if (matchedVessel) setVesselId(matchedVessel.id);
  }

  async function uploadAndExtract() {
    setError("");
    if (!intakeFile) {
      setError("Choose a PDF, JPG, PNG or DOCX claim notification first.");
      return;
    }
    setExtracting(true);
    setIntakeDraft(null);
    try {
      let draft = await uploadClaimIntakeDraft(intakeFile);
      setIntakeDraft(draft);
      for (let attempt = 0; attempt < 60 && draft.status === "processing"; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        draft = await getClaimIntakeDraft(draft.id);
        setIntakeDraft(draft);
      }
      if (draft.status !== "pending_review") {
        throw new ApiError(409, draft.extraction_warnings?.[0] ?? "The document could not be prepared for review.");
      }
      applyCandidates(draft);
      setReviewNote("I reviewed the proposed fields against the uploaded source document.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not prepare the intake document.");
    } finally {
      setExtracting(false);
    }
  }

  async function addVessel() {
    setError("");
    if (vesselName.trim().length < 2) {
      setError("Enter a vessel name.");
      return;
    }
    try {
      const vessel = await createVessel({ name: vesselName.trim(), imo_number: imo.trim() || null });
      setVessels((current) => [...current, vessel].sort((a, b) => a.name.localeCompare(b.name)));
      setVesselId(vessel.id);
      setShowNewVessel(false);
      setVesselName("");
      setImo("");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not create vessel.");
    }
  }

  async function rejectDraft() {
    if (!intakeDraft || reviewNote.trim().length < 10) {
      setError("Enter a review note of at least 10 characters before rejecting the draft.");
      return;
    }
    setSubmitting(true);
    try {
      const rejected = await rejectClaimIntakeDraft(intakeDraft.id, reviewNote.trim());
      setIntakeDraft(rejected);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reject the intake draft.");
    } finally {
      setSubmitting(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!vesselId) {
      setError("Select or create a vessel first.");
      return;
    }
    if (mode === "document" && intakeDraft?.status !== "pending_review") {
      setError("Upload and process a source document before approving this claim.");
      return;
    }
    if (mode === "document" && reviewNote.trim().length < 10) {
      setError("Record a review note of at least 10 characters.");
      return;
    }
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
          document_type: intakeDraft.classification_candidate || "claim_notification",
          review_note: reviewNote.trim(),
        });
        router.push(`/claims/${result.claim.id}`);
      } else {
        const claim = await createClaim(claimPayload);
        router.push(`/claims/${claim.id}`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not create claim.");
    } finally {
      setSubmitting(false);
    }
  }

  const pendingReview = intakeDraft?.status === "pending_review";

  return (
    <div className="max-w-5xl">
      <Link href="/claims" className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claims</Link>
      <div className="mt-4">
        <p className="eyebrow">New case</p>
        <h1 className="page-title">Create H&amp;M machinery claim</h1>
        <p className="page-subtitle">Import a claim notification for review, or enter the incident manually.</p>
      </div>

      <div className="mt-6 inline-flex rounded-xl border border-slate-200 bg-white p-1">
        <button type="button" onClick={() => setMode("document")} className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === "document" ? "bg-slate-900 text-white" : "text-slate-600"}`}>Import notification</button>
        <button type="button" onClick={() => setMode("manual")} className={`rounded-lg px-4 py-2 text-sm font-semibold ${mode === "manual" ? "bg-slate-900 text-white" : "text-slate-600"}`}>Manual entry</button>
      </div>

      <form onSubmit={submit} className="mt-5 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          {mode === "document" ? (
            <section className="panel p-6">
              <h2 className="section-title">1. Secure source intake</h2>
              <p className="section-subtitle">The file is scanned first. English/Persian OCR and extracted values remain proposals until you approve them.</p>
              <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                <input type="file" accept=".pdf,.jpg,.jpeg,.png,.docx" onChange={(event) => setIntakeFile(event.target.files?.[0] ?? null)} className="field flex-1" />
                <button type="button" onClick={uploadAndExtract} disabled={extracting} className="secondary-button justify-center disabled:opacity-60">{extracting ? "Scanning & extracting…" : "Upload & extract"}</button>
              </div>
              {intakeDraft ? (
                <div className={`mt-4 rounded-xl border p-4 text-sm ${pendingReview ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2"><strong>{intakeDraft.original_filename}</strong><span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold">{intakeDraft.status.replaceAll("_", " ")}</span></div>
                  {pendingReview ? <p className="mt-2">Suggested type: {intakeDraft.classification_candidate?.replaceAll("_", " ") || "unknown"} · confidence {intakeDraft.classification_confidence ?? 0}% · method {intakeDraft.extraction_method}</p> : null}
                  {intakeDraft.extraction_warnings?.map((warning) => <p key={warning} className="mt-2 text-amber-800">{warning}</p>)}
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="panel p-6">
            <h2 className="section-title">{mode === "document" ? "2. Review vessel" : "Vessel"}</h2>
            <p className="section-subtitle">A human must match the proposal to an existing tenant vessel or create one explicitly.</p>
            <div className="mt-5 flex gap-3"><select required value={vesselId} onChange={(event) => setVesselId(event.target.value)} className="field flex-1"><option value="">Select vessel…</option>{vessels.map((vessel) => <option key={vessel.id} value={vessel.id}>{vessel.name}{vessel.imo_number ? ` · IMO ${vessel.imo_number}` : ""}</option>)}</select><button type="button" onClick={() => setShowNewVessel(!showNewVessel)} className="secondary-button whitespace-nowrap">+ Vessel</button></div>
            {showNewVessel ? <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_180px_auto]"><input className="field" value={vesselName} onChange={(event) => setVesselName(event.target.value)} placeholder="Vessel name" /><input className="field" value={imo} onChange={(event) => setImo(event.target.value.replace(/\D/g, "").slice(0, 7))} placeholder="IMO number" /><button type="button" onClick={addVessel} className="secondary-button">Add</button></div> : null}
          </section>

          <section className="panel p-6">
            <h2 className="section-title">{mode === "document" ? "3. Review incident" : "Incident"}</h2>
            <p className="section-subtitle">Compare every prefilled value with the source. Editing here does not create an approved Claim Fact.</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2"><label><span className="label">Incident date</span><input required type="date" value={incidentDate} onChange={(event) => setIncidentDate(event.target.value)} className="field" /></label><label><span className="label">Notification date</span><input required type="date" value={notificationDate} onChange={(event) => setNotificationDate(event.target.value)} className="field" /></label></div>
            <label className="mt-4 block"><span className="label">Incident description</span><textarea required minLength={10} rows={6} value={description} onChange={(event) => setDescription(event.target.value)} className="field resize-y" placeholder="Describe the machinery incident…" /></label>
          </section>

          <section className="panel p-6">
            <h2 className="section-title">Exposure</h2>
            <p className="section-subtitle">Optional preliminary commercial information; no reserve or coverage decision is automated.</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2"><label><span className="label">Estimated loss</span><input type="number" min="0" step="0.01" value={estimatedLoss} onChange={(event) => setEstimatedLoss(event.target.value)} className="field" placeholder="550000" /></label><label><span className="label">Currency</span><input required minLength={3} maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} className="field uppercase" /></label><label><span className="label">External reference</span><input value={externalReference} onChange={(event) => setExternalReference(event.target.value)} className="field" placeholder="Insurer / broker reference" /></label><label><span className="label">Priority</span><select value={priority} onChange={(event) => setPriority(event.target.value as typeof priority)} className="field"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label></div>
          </section>

          {mode === "document" ? (
            <section className="panel p-6">
              <h2 className="section-title">4. Human approval</h2>
              <p className="section-subtitle">Record what you checked. Approval creates one claim and links the clean source document.</p>
              <label className="mt-5 block"><span className="label">Review note</span><textarea required minLength={10} rows={3} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} className="field resize-y" /></label>
              {pendingReview ? <button type="button" disabled={submitting} onClick={rejectDraft} className="mt-3 text-sm font-semibold text-red-700 hover:text-red-900">Reject this draft without creating a claim</button> : null}
            </section>
          ) : null}
        </div>

        <aside><div className="panel sticky top-24 p-5"><p className="text-sm font-semibold text-slate-900">Human-controlled intake</p><dl className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-4"><dt className="text-slate-500">Claim type</dt><dd className="font-medium">H&amp;M</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">Source</dt><dd className="font-medium">{mode === "document" ? "Reviewed upload" : "Manual"}</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">Initial status</dt><dd className="font-medium">New</dd></div></dl><div className="my-5 border-t border-slate-200" />{error ? <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}<button disabled={submitting || extracting || (mode === "document" && !pendingReview)} className="primary-button w-full justify-center disabled:opacity-60">{submitting ? "Creating…" : mode === "document" ? "Approve & create claim" : "Create claim"}</button><p className="mt-3 text-xs leading-5 text-slate-400">No candidate becomes claim truth automatically. A unique MCRI reference is generated only after approval.</p></div></aside>
      </form>
    </div>
  );
}
