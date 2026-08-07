"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, createClaim, createVessel, listVessels } from "@/lib/api";
import type { Vessel } from "@/lib/types";

export default function NewClaimPage() {
  const router = useRouter();
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
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => { listVessels().then((r) => { setVessels(r.items); if (r.items[0]) setVesselId(r.items[0].id); }); }, []);

  async function addVessel() {
    setError("");
    if (vesselName.trim().length < 2) { setError("Enter a vessel name."); return; }
    try {
      const vessel = await createVessel({ name: vesselName.trim(), imo_number: imo.trim() || null });
      setVessels((current) => [...current, vessel].sort((a, b) => a.name.localeCompare(b.name)));
      setVesselId(vessel.id);
      setShowNewVessel(false);
      setVesselName(""); setImo("");
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not create vessel."); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!vesselId) { setError("Select or create a vessel first."); return; }
    setSubmitting(true);
    try {
      const claim = await createClaim({
        vessel_id: vesselId,
        incident_date: incidentDate,
        notification_date: notificationDate,
        incident_description: description,
        claim_type: "hull_machinery",
        claim_subtype: "machinery_damage",
        priority,
        external_reference: externalReference.trim() || null,
        estimated_loss: estimatedLoss ? Number(estimatedLoss) : null,
        currency: currency.toUpperCase(),
      });
      router.push(`/claims/${claim.id}`);
    } catch (err) { setError(err instanceof ApiError ? err.detail : "Could not create claim."); }
    finally { setSubmitting(false); }
  }

  return (
    <div className="max-w-5xl">
      <Link href="/claims" className="text-sm font-semibold text-slate-500 hover:text-slate-800">← Back to claims</Link>
      <div className="mt-4"><p className="eyebrow">New case</p><h1 className="page-title">Create H&M machinery claim</h1><p className="page-subtitle">Start with the essential incident data. Detailed evidence is added later.</p></div>

      <form onSubmit={submit} className="mt-7 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <section className="panel p-6"><h2 className="section-title">Vessel</h2><p className="section-subtitle">Choose the insured vessel connected to this incident.</p>
            <div className="mt-5 flex gap-3"><select value={vesselId} onChange={(e) => setVesselId(e.target.value)} className="field flex-1"><option value="">Select vessel…</option>{vessels.map((v) => <option key={v.id} value={v.id}>{v.name}{v.imo_number ? ` · IMO ${v.imo_number}` : ""}</option>)}</select><button type="button" onClick={() => setShowNewVessel(!showNewVessel)} className="secondary-button whitespace-nowrap">+ Vessel</button></div>
            {showNewVessel ? <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_180px_auto]"><input className="field" value={vesselName} onChange={(e) => setVesselName(e.target.value)} placeholder="Vessel name" /><input className="field" value={imo} onChange={(e) => setImo(e.target.value.replace(/\D/g, "").slice(0,7))} placeholder="IMO number" /><button type="button" onClick={addVessel} className="secondary-button">Add</button></div> : null}
          </section>

          <section className="panel p-6"><h2 className="section-title">Incident</h2><p className="section-subtitle">The minimum facts required to open the claim.</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2"><label><span className="label">Incident date</span><input required type="date" value={incidentDate} onChange={(e) => setIncidentDate(e.target.value)} className="field" /></label><label><span className="label">Notification date</span><input required type="date" value={notificationDate} onChange={(e) => setNotificationDate(e.target.value)} className="field" /></label></div>
            <label className="mt-4 block"><span className="label">Incident description</span><textarea required minLength={10} rows={6} value={description} onChange={(e) => setDescription(e.target.value)} className="field resize-y" placeholder="Example: Main engine turbocharger No.2 developed abnormal vibration and elevated exhaust temperature during voyage…" /></label>
          </section>

          <section className="panel p-6"><h2 className="section-title">Exposure</h2><p className="section-subtitle">Optional preliminary commercial information.</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2"><label><span className="label">Estimated loss</span><input type="number" min="0" step="0.01" value={estimatedLoss} onChange={(e) => setEstimatedLoss(e.target.value)} className="field" placeholder="550000" /></label><label><span className="label">Currency</span><input maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} className="field uppercase" /></label><label><span className="label">External reference</span><input value={externalReference} onChange={(e) => setExternalReference(e.target.value)} className="field" placeholder="Insurer / broker reference" /></label><label><span className="label">Priority</span><select value={priority} onChange={(e) => setPriority(e.target.value as typeof priority)} className="field"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label></div>
          </section>
        </div>

        <aside><div className="panel sticky top-24 p-5"><p className="text-sm font-semibold text-slate-900">MVP claim profile</p><dl className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-4"><dt className="text-slate-500">Claim type</dt><dd className="font-medium">H&M</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">Subtype</dt><dd className="font-medium">Machinery damage</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">Initial status</dt><dd className="font-medium">New</dd></div></dl><div className="my-5 border-t border-slate-200" />{error ? <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}<button disabled={submitting} className="primary-button w-full justify-center disabled:opacity-60">{submitting ? "Creating…" : "Create claim"}</button><p className="mt-3 text-xs leading-5 text-slate-400">A unique MCRI reference is generated automatically after creation.</p></div></aside>
      </form>
    </div>
  );
}
