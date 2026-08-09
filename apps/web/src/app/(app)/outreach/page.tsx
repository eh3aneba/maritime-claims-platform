"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, createDesignPartnerAccount, getDesignPartnerCohort } from "@/lib/api";
import type { DesignPartnerCohortSummary } from "@/lib/types";

const scoreLabels = [
  ["machinery_claim_volume_score", "Machinery claim volume"], ["pain_intensity_score", "Pain intensity"], ["buyer_access_score", "Buyer access"],
  ["data_availability_score", "Data availability"], ["security_fit_score", "Security fit"], ["pilot_willingness_score", "Pilot willingness"],
] as const;

export default function OutreachPage() {
  const [data, setData] = useState<DesignPartnerCohortSummary | null>(null);
  const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function refresh(){ try { setData(await getDesignPartnerCohort()); setError(""); } catch(e){ setError(e instanceof ApiError ? e.detail : "Could not load cohort."); } }
  useEffect(()=>{ refresh(); },[]);
  async function addAccount(event: FormEvent<HTMLFormElement>){ event.preventDefault(); setSaving(true); const form=new FormData(event.currentTarget); const payload:Record<string,unknown>={name:form.get("name"),account_type:form.get("account_type")}; for(const [key] of scoreLabels) payload[key]=Number(form.get(key)||0); try{ await createDesignPartnerAccount(payload); event.currentTarget.reset(); await refresh(); }catch(e){setError(e instanceof ApiError?e.detail:"Could not add account.");} finally{setSaving(false);} }
  return <div className="space-y-7">
    <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">Founder GTM</p><h1 className="mt-1 text-2xl font-bold">Design Partner Cohort</h1><p className="mt-2 max-w-3xl text-sm text-slate-600">Prioritize H&M-heavy accounts. The score ranks founder attention; it does not predict purchase probability.</p></div>
    {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    {data && <div className="grid gap-4 md:grid-cols-4">
      {[['Accounts',data.accounts_total],['A-tier',data.a_tier],['Pilot qualified',`${data.pilot_qualified}/${data.target_qualified_partners}`],['Paid pilots',`${data.paid_pilots}/${data.target_paid_pilots}`]].map(([l,v])=><div key={String(l)} className="rounded-xl border bg-white p-5"><div className="text-xs uppercase tracking-wide text-slate-400">{l}</div><div className="mt-2 text-2xl font-bold">{v}</div></div>)}
    </div>}
    <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <div className="overflow-hidden rounded-xl border bg-white"><div className="border-b px-5 py-4 font-semibold">Ranked target accounts</div><div className="divide-y">
        {data?.accounts.length ? data.accounts.map(a=><div key={a.id} className="grid gap-3 px-5 py-4 md:grid-cols-[1.5fr_.6fr_.8fr_1.4fr]"><div><div className="font-semibold">{a.name}</div><div className="text-xs text-slate-500">{a.account_type.replaceAll('_',' ')} · {a.stage.replaceAll('_',' ')}</div></div><div><span className="rounded-md bg-slate-900 px-2 py-1 text-xs font-bold text-white">{a.qualification_band} · {a.qualification_score}</span></div><div className="text-sm text-slate-600">{a.next_step || 'No next step yet'}</div><div className="text-xs leading-5 text-slate-500">{a.recommended_action}</div></div>) : <div className="p-8 text-sm text-slate-500">No target accounts yet.</div>}
      </div></div>
      <form onSubmit={addAccount} className="rounded-xl border bg-white p-5"><h2 className="font-semibold">Add target account</h2><label className="mt-4 block text-xs font-semibold text-slate-500">Account name</label><input name="name" required className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"/><label className="mt-4 block text-xs font-semibold text-slate-500">Type</label><select name="account_type" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"><option value="marine_insurer">Marine insurer</option><option value="ship_manager">Ship manager</option><option value="p_and_i_correspondent">P&I correspondent</option><option value="average_adjuster">Average adjuster</option></select><div className="mt-4 space-y-3">{scoreLabels.map(([key,label])=><label key={key} className="grid grid-cols-[1fr_70px] items-center gap-3 text-xs text-slate-600"><span>{label}</span><input name={key} type="number" min="0" max="5" defaultValue="0" className="rounded border px-2 py-1.5"/></label>)}</div><button disabled={saving} className="mt-5 w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving?'Saving…':'Add and score'}</button></form>
    </div>
  </div>;
}
