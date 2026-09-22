"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE, ApiError } from "@/lib/api";

type Profile = {
  profile_id: string;
  provider_kind: string;
  display_name: string;
  profile_status: string;
  provider_health_status: string | null;
  provider_health_latency_class: string | null;
  provider_health_completed_at: string | null;
  active_family_count: number;
  pending_handoff_count: number;
  processing_release_required_count: number;
  next_due_at: string | null;
  last_observation_completed_at: string | null;
};

type Family = {
  binding_id: string;
  claim_id: string;
  profile_id: string;
  provider_kind: string;
  document_family_id: string;
  current_document_id: string;
  current_version_number: number;
  schedule_id: string | null;
  schedule_status: string | null;
  next_due_at: string | null;
  last_observation_id: string | null;
  last_observation_result: string | null;
  last_observation_completed_at: string | null;
  pending_handoff_id: string | null;
  pending_handoff_kind: string | null;
  pending_handoff_projected_at: string | null;
  latest_decision_kind: string | null;
  latest_decision_status: string | null;
  latest_decided_at: string | null;
  latest_refresh_status: string | null;
  latest_refresh_completed_at: string | null;
  latest_admission_authorization_status: string | null;
  latest_admission_status: string | null;
  latest_admission_executed_at: string | null;
  processing_release_status: string | null;
  processing_release_required: boolean;
};

type Overview = { profiles: Profile[]; families: Family[] };

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function when(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString();
}

function badge(value: string | null, fallback = "not recorded") {
  return (value ?? fallback).replaceAll("_", " ");
}

export default function ExternalEvidencePage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "attention" | "release">("all");

  const load = useCallback(async () => {
    try {
      setOverview(await request<Overview>("/external-document-sources/operator-overview"));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not load external Evidence operations.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const families = useMemo(() => {
    const rows = overview?.families ?? [];
    if (filter === "attention") return rows.filter((row) => row.pending_handoff_id);
    if (filter === "release") return rows.filter((row) => row.processing_release_required);
    return rows;
  }, [overview, filter]);

  const pending = overview?.families.filter((row) => row.pending_handoff_id).length ?? 0;
  const releaseRequired = overview?.families.filter((row) => row.processing_release_required).length ?? 0;
  const scheduled = overview?.families.filter((row) => row.schedule_status === "active").length ?? 0;

  return (
    <div className="space-y-7">
      <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
          External Evidence · Phase 17.5-AK
        </p>
        <h1 className="mt-3 text-3xl font-semibold">SharePoint & Google Drive operations</h1>
        <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">
          One operational view of source health, recurring observation, human review, refresh admission,
          canonical version lineage and the separate processing-release requirement. This screen is
          non-authoritative: every action still belongs to its own governed API and approval boundary.
        </p>
      </section>

      {error && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Source profiles", overview?.profiles.length ?? 0],
          ["Active schedules", scheduled],
          ["Needs human review", pending],
          ["Phase-Z release required", releaseRequired],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
            <p className="mt-2 text-2xl font-semibold">{value}</p>
          </div>
        ))}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Provider profiles</h2>
            <p className="mt-1 text-sm text-slate-500">Health is a bounded provider qualification; it is not admission authority.</p>
          </div>
          <button onClick={() => void load()} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold hover:bg-slate-50">
            Refresh view
          </button>
        </div>
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          {(overview?.profiles ?? []).map((profile) => (
            <article key={profile.profile_id} className="rounded-xl border border-slate-200 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="font-semibold">{profile.display_name}</h3>
                  <p className="mt-1 text-xs uppercase tracking-wide text-slate-500">{profile.provider_kind.replaceAll("_", " ")}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold capitalize text-slate-700">
                  {badge(profile.profile_status)}
                </span>
              </div>
              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                <div><dt className="text-slate-500">Provider health</dt><dd className="font-medium capitalize">{badge(profile.provider_health_status)}</dd></div>
                <div><dt className="text-slate-500">Health checked</dt><dd>{when(profile.provider_health_completed_at)}</dd></div>
                <div><dt className="text-slate-500">Active families</dt><dd>{profile.active_family_count}</dd></div>
                <div><dt className="text-slate-500">Pending handoffs</dt><dd>{profile.pending_handoff_count}</dd></div>
                <div><dt className="text-slate-500">Next due</dt><dd>{when(profile.next_due_at)}</dd></div>
                <div><dt className="text-slate-500">Last observation</dt><dd>{when(profile.last_observation_completed_at)}</dd></div>
              </dl>
            </article>
          ))}
          {overview && overview.profiles.length === 0 && <p className="text-sm text-slate-500">No external source profiles are configured.</p>}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Bound Evidence families</h2>
            <p className="mt-1 text-sm text-slate-500">Current N/N+1 version, recurring watch and separated human-control checkpoints.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["all", "attention", "release"] as const).map((value) => (
              <button
                key={value}
                onClick={() => setFilter(value)}
                className={`rounded-lg px-3 py-2 text-sm font-semibold ${filter === value ? "bg-slate-900 text-white" : "border border-slate-300 text-slate-700"}`}
              >
                {value === "all" ? "All" : value === "attention" ? "Human review" : "Phase-Z required"}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="min-w-[1180px] w-full border-separate border-spacing-0 text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-slate-500">
                {["Claim / provider", "Current Evidence", "Schedule", "Observation", "Human review", "Refresh / admission", "Processing"].map((label) => (
                  <th key={label} className="border-b border-slate-200 px-3 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {families.map((row) => (
                <tr key={row.binding_id} className="align-top">
                  <td className="border-b border-slate-100 px-3 py-4">
                    <div className="font-mono text-xs">{row.claim_id.slice(0, 8)}…</div>
                    <div className="mt-1 capitalize text-slate-500">{row.provider_kind.replaceAll("_", " ")}</div>
                  </td>
                  <td className="border-b border-slate-100 px-3 py-4">
                    <div className="font-semibold">Version {row.current_version_number}</div>
                    <div className="mt-1 font-mono text-[11px] text-slate-500">{row.current_document_id.slice(0, 8)}…</div>
                  </td>
                  <td className="border-b border-slate-100 px-3 py-4">
                    <div className="capitalize">{badge(row.schedule_status)}</div>
                    <div className="mt-1 text-xs text-slate-500">{when(row.next_due_at)}</div>
                  </td>
                  <td className="border-b border-slate-100 px-3 py-4">
                    <div className="capitalize">{badge(row.last_observation_result)}</div>
                    <div className="mt-1 text-xs text-slate-500">{when(row.last_observation_completed_at)}</div>
                  </td>
                  <td className="border-b border-slate-100 px-3 py-4">
                    {row.pending_handoff_id ? (
                      <div>
                        <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold capitalize text-amber-900">
                          {badge(row.pending_handoff_kind)}
                        </span>
                        <div className="mt-2 text-xs text-slate-500">AG decision required</div>
                      </div>
                    ) : (
                      <div>
                        <span className="capitalize">{badge(row.latest_decision_status, "none pending")}</span>
                        <div className="mt-1 text-xs text-slate-500">{row.latest_decision_kind ? badge(row.latest_decision_kind) : "No open handoff"}</div>
                      </div>
                    )}
                  </td>
                  <td className="border-b border-slate-100 px-3 py-4">
                    <div className="text-xs text-slate-500">Refresh</div>
                    <div className="capitalize">{badge(row.latest_refresh_status)}</div>
                    <div className="mt-2 text-xs text-slate-500">AH authorization</div>
                    <div className="capitalize">{badge(row.latest_admission_authorization_status)}</div>
                    <div className="mt-2 text-xs text-slate-500">AJ admission</div>
                    <div className="capitalize">{badge(row.latest_admission_status)}</div>
                  </td>
                  <td className="border-b border-slate-100 px-3 py-4">
                    {row.processing_release_required ? (
                      <span className="rounded-full bg-rose-100 px-2 py-1 text-xs font-semibold text-rose-900">Phase-Z required</span>
                    ) : (
                      <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-900">Released</span>
                    )}
                    <div className="mt-2 text-xs capitalize text-slate-500">{badge(row.processing_release_status)}</div>
                  </td>
                </tr>
              ))}
              {overview && families.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-slate-500">No Evidence families match this filter.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
        <strong>Authority boundary:</strong> changed and missing observations never update or delete canonical Evidence automatically.
        AG review, refresh execution, AH admission authorization, AJ canonical admission and Phase-Z processing release remain separate steps.
      </section>
    </div>
  );
}
