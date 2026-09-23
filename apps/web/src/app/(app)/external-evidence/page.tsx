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

type Version = {
  document_id: string;
  version_number: number;
  is_current: boolean;
  processing_status: string;
  created_at: string;
  superseded_at: string | null;
  processing_release_status: string | null;
  processing_release_required: boolean;
};

type Family = {
  binding_id: string;
  claim_id: string;
  profile_id: string;
  provider_kind: string;
  document_family_id: string;
  current_document_id: string;
  current_version_number: number;
  version_history: Version[];
  schedule_id: string | null;
  schedule_status: string | null;
  next_due_at: string | null;
  last_observation_id: string | null;
  last_observation_result: string | null;
  last_observation_completed_at: string | null;
  pending_handoff_id: string | null;
  pending_handoff_kind: string | null;
  pending_handoff_projected_at: string | null;
  latest_decision_id: string | null;
  latest_decision_kind: string | null;
  latest_decision_status: string | null;
  latest_decided_at: string | null;
  refresh_authorization_id: string | null;
  refresh_authorization_status: string | null;
  refresh_execution_required: boolean;
  latest_refresh_execution_id: string | null;
  latest_refresh_status: string | null;
  latest_refresh_completed_at: string | null;
  latest_refresh_failure_code: string | null;
  latest_refresh_failed_at: string | null;
  latest_admission_authorization_id: string | null;
  latest_admission_authorization_status: string | null;
  admission_authorization_required: boolean;
  latest_admission_execution_id: string | null;
  admission_execution_required: boolean;
  latest_admission_status: string | null;
  latest_admission_executed_at: string | null;
  processing_release_status: string | null;
  processing_release_required: boolean;
};

type Overview = { profiles: Profile[]; families: Family[] };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
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

function processingReleaseLabel(value: string | null) {
  return value === "active" ? "released" : badge(value, "released");
}

function requestKey(prefix: string) {
  return `ak-${prefix}-${crypto.randomUUID()}`;
}

export default function ExternalEvidencePage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
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

  function noteFor(row: Family) {
    return (notes[row.binding_id] ?? "").trim();
  }

  function noteReady(row: Family) {
    return noteFor(row).length >= 20;
  }

  async function runAction(
    key: string,
    path: string,
    body: Record<string, unknown>,
    success: string,
  ) {
    setBusy(key);
    setError(null);
    setMessage(null);
    try {
      await request(path, { method: "POST", body: JSON.stringify(body) });
      setMessage(success);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "The governed external Evidence action failed.");
    } finally {
      setBusy(null);
    }
  }

  async function decideHandoff(row: Family, decisionKind: "approve_refresh" | "dismiss" | "acknowledge_missing") {
    if (!row.pending_handoff_id || !noteReady(row)) return;
    await runAction(
      `ag-${row.binding_id}-${decisionKind}`,
      `/external-document-sources/profiles/${row.profile_id}/observation-review-handoffs/${row.pending_handoff_id}/decisions`,
      {
        request_key: requestKey("ag"),
        decision_kind: decisionKind,
        reason: noteFor(row),
      },
      decisionKind === "approve_refresh"
        ? "AG approval recorded. The exact refresh authorization is now separate and single-use."
        : decisionKind === "acknowledge_missing"
          ? "Missing-source observation acknowledged. Canonical Evidence was not deleted or invalidated."
          : "Observation handoff dismissed without canonical Evidence mutation.",
    );
  }

  async function executeRefresh(row: Family) {
    if (!row.refresh_authorization_id || !noteReady(row)) return;
    await runAction(
      `ah-${row.binding_id}`,
      `/external-document-sources/profiles/${row.profile_id}/observation-refresh-authorizations/${row.refresh_authorization_id}/execute`,
      { request_key: requestKey("ah"), reason: noteFor(row) },
      "Phase-AH exact refresh completed and staged. No canonical Evidence was admitted.",
    );
  }

  async function authorizeAdmission(row: Family) {
    if (!row.latest_refresh_execution_id || !noteReady(row)) return;
    await runAction(
      `ai-${row.binding_id}`,
      `/external-document-sources/profiles/${row.profile_id}/observation-refresh-executions/${row.latest_refresh_execution_id}/admission-authorizations`,
      { request_key: requestKey("ai"), reason: noteFor(row) },
      "Phase-AI admission authorization recorded for this exact staged refresh. No external AI was run.",
    );
  }

  async function executeAdmission(row: Family) {
    if (!row.latest_admission_authorization_id || !noteReady(row)) return;
    await runAction(
      `aj-${row.binding_id}`,
      `/external-document-sources/profiles/${row.profile_id}/evidence-family-bindings/${row.binding_id}/observation-refresh-admissions/${row.latest_admission_authorization_id}`,
      { request_key: requestKey("aj"), reason: noteFor(row) },
      "Phase-AJ canonical N+1 admission completed. The new exact version still requires its own Phase-Z release.",
    );
  }

  return (
    <div className="space-y-7">
      <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
          External Evidence · Phase 17.5-AK
        </p>
        <h1 className="mt-3 text-3xl font-semibold">SharePoint & Google Drive operations</h1>
        <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">
          One operational view of source health, recurring observation, human review, exact refresh,
          admission authorization, canonical version lineage and the separate processing-release requirement.
          Every mutation below calls its own governed API; there is deliberately no “sync everything” action.
        </p>
      </section>

      {(error || message) && (
        <div
          role={error ? "alert" : "status"}
          className={`rounded-xl border px-4 py-3 text-sm ${
            error
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {error ?? message}
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
            <p className="mt-1 text-sm text-slate-500">Current and historical versions plus separate AG → AH → AI → AJ controls.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["all", "attention", "release"] as const).map((value) => (
              <button
                key={value}
                onClick={() => setFilter(value)}
                className={`rounded-lg px-3 py-2 text-sm font-semibold ${
                  filter === value ? "bg-slate-900 text-white" : "border border-slate-300 text-slate-700"
                }`}
              >
                {value === "all" ? "All" : value === "attention" ? "Human review" : "Phase-Z required"}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="min-w-[1540px] w-full border-separate border-spacing-0 text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-slate-500">
                {[
                  "Claim / provider",
                  "Evidence lineage",
                  "Schedule",
                  "Observation",
                  "AG review",
                  "AH / AI / AJ",
                  "Processing",
                  "Governed action",
                ].map((label) => (
                  <th key={label} className="border-b border-slate-200 px-3 py-3 font-semibold">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {families.map((row) => {
                const isChanged = row.pending_handoff_kind === "changed";
                const isMissing = row.pending_handoff_kind === "missing";
                const hasRefreshToRun = row.refresh_execution_required;
                const hasAdmissionToAuthorize = row.admission_authorization_required;
                const hasAdmissionToRun = row.admission_execution_required;
                const actionDisabled = busy !== null || !noteReady(row);

                return (
                  <tr key={row.binding_id} className="align-top">
                    <td className="border-b border-slate-100 px-3 py-4">
                      <div className="font-mono text-xs">{row.claim_id.slice(0, 8)}…</div>
                      <div className="mt-1 capitalize text-slate-500">{row.provider_kind.replaceAll("_", " ")}</div>
                    </td>
                    <td className="border-b border-slate-100 px-3 py-4">
                      <div className="font-semibold">Current v{row.current_version_number}</div>
                      <div className="mt-1 font-mono text-[11px] text-slate-500">{row.current_document_id.slice(0, 8)}…</div>
                      <div className="mt-3 space-y-1">
                        {row.version_history.length ? row.version_history.map((version) => (
                          <div key={version.document_id} className="text-xs text-slate-600">
                            v{version.version_number} · {version.is_current ? "current" : "historical"} ·
                            {" "}{version.processing_release_required ? "Phase-Z required" : processingReleaseLabel(version.processing_release_status)}
                          </div>
                        )) : <div className="text-xs text-slate-400">No lineage rows loaded.</div>}
                      </div>
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
                          <div className="mt-2 text-xs text-slate-500">AG human decision required</div>
                        </div>
                      ) : (
                        <div>
                          <span className="capitalize">{badge(row.latest_decision_status, "none pending")}</span>
                          <div className="mt-1 text-xs text-slate-500">
                            {row.latest_decision_kind ? badge(row.latest_decision_kind) : "No open handoff"}
                          </div>
                        </div>
                      )}
                    </td>
                    <td className="border-b border-slate-100 px-3 py-4">
                      <div className="text-xs font-semibold text-slate-500">AH · exact refresh / staging</div>
                      <div className="capitalize">{badge(row.latest_refresh_status)}</div>
                      {row.latest_refresh_failure_code && (
                        <div className="mt-1 text-xs text-rose-700">
                          {badge(row.latest_refresh_failure_code)} · {when(row.latest_refresh_failed_at)}
                        </div>
                      )}
                      <div className="mt-3 text-xs font-semibold text-slate-500">AI · admission authorization</div>
                      <div className="capitalize">{badge(row.latest_admission_authorization_status)}</div>
                      <div className="mt-3 text-xs font-semibold text-slate-500">AJ · canonical N+1 admission</div>
                      <div className="capitalize">{badge(row.latest_admission_status)}</div>
                      <div className="mt-1 text-[11px] text-slate-400">Phase-AI is an A→AJ workflow label; it does not execute external artificial intelligence.</div>
                    </td>
                    <td className="border-b border-slate-100 px-3 py-4">
                      {row.processing_release_required ? (
                        <span className="rounded-full bg-rose-100 px-2 py-1 text-xs font-semibold text-rose-900">Phase-Z required</span>
                      ) : (
                        <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-900">Released</span>
                      )}
                      <div className="mt-2 text-xs capitalize text-slate-500">{badge(row.processing_release_status)}</div>
                    </td>
                    <td className="border-b border-slate-100 px-3 py-4">
                      <label className="block text-xs font-semibold text-slate-600" htmlFor={`note-${row.binding_id}`}>
                        Human reason / audit note
                      </label>
                      <textarea
                        id={`note-${row.binding_id}`}
                        value={notes[row.binding_id] ?? ""}
                        onChange={(event) => setNotes((current) => ({ ...current, [row.binding_id]: event.target.value }))}
                        placeholder="Enter at least 20 characters before a governed action."
                        className="mt-2 min-h-20 w-72 rounded-lg border border-slate-300 px-3 py-2 text-xs"
                      />
                      <div className="mt-2 flex w-72 flex-wrap gap-2">
                        {row.pending_handoff_id && isChanged && (
                          <>
                            <button
                              disabled={actionDisabled}
                              onClick={() => void decideHandoff(row, "approve_refresh")}
                              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                            >
                              AG · Approve refresh
                            </button>
                            <button
                              disabled={actionDisabled}
                              onClick={() => void decideHandoff(row, "dismiss")}
                              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                            >
                              AG · Dismiss
                            </button>
                          </>
                        )}
                        {row.pending_handoff_id && isMissing && (
                          <>
                            <button
                              disabled={actionDisabled}
                              onClick={() => void decideHandoff(row, "acknowledge_missing")}
                              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                            >
                              AG · Acknowledge missing
                            </button>
                            <button
                              disabled={actionDisabled}
                              onClick={() => void decideHandoff(row, "dismiss")}
                              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                            >
                              AG · Dismiss
                            </button>
                          </>
                        )}
                        {hasRefreshToRun && (
                          <button
                            disabled={actionDisabled}
                            onClick={() => void executeRefresh(row)}
                            className="rounded-md bg-cyan-800 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                          >
                            AH · Read & stage exact refresh
                          </button>
                        )}
                        {hasAdmissionToAuthorize && (
                          <button
                            disabled={actionDisabled}
                            onClick={() => void authorizeAdmission(row)}
                            className="rounded-md bg-indigo-800 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                          >
                            AI · Authorize exact admission
                          </button>
                        )}
                        {hasAdmissionToRun && (
                          <button
                            disabled={actionDisabled}
                            onClick={() => void executeAdmission(row)}
                            className="rounded-md bg-emerald-800 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                          >
                            AJ · Admit canonical N+1
                          </button>
                        )}
                        {!row.pending_handoff_id && !hasRefreshToRun && !hasAdmissionToAuthorize && !hasAdmissionToRun && (
                          <span className="text-xs text-slate-400">No governed action is currently due.</span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {overview && families.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-500">No Evidence families match this filter.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
        <strong>Authority boundary:</strong> changed and missing observations never update or delete canonical Evidence automatically.
        AG review, AH exact refresh/staging, AI admission authorization, AJ canonical admission and Phase-Z processing release remain separate.
        No action on this page grants external-AI execution authority.
      </section>
    </div>
  );
}
