"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { listMatureAdjustments, type MatureAdjustmentStatement } from "@/lib/adjustment-maturity-api";
import { ApiError, getClaim, getCurrentUser } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { reviewT } from "@/lib/i18n-review-support";
import {
  getAuthoritativeReserveHistory,
  recordAuthoritativeReserve,
  type ReserveHistoryResponse,
  type ReserveSourceKind,
} from "@/lib/reserve-lineage-api";
import {
  buildSeverityReserve,
  getSeverityReserve,
  type SeverityReserveSnapshot,
} from "@/lib/severity-reserve-api";
import type { Claim, CurrentUser } from "@/lib/types";

function newIdempotencyKey() {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `reserve-${random}`;
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—";
}

export default function AuthoritativeReservePage() {
  const { id } = useParams<{ id: string }>();
  const { locale } = useLocale();
  const r = (en: string, fa: string) => reviewT(locale, en, fa);

  const [claim, setClaim] = useState<Claim | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [history, setHistory] = useState<ReserveHistoryResponse | null>(null);
  const [support, setSupport] = useState<SeverityReserveSnapshot | null>(null);
  const [adjustments, setAdjustments] = useState<MatureAdjustmentStatement[]>([]);
  const [sourceKind, setSourceKind] = useState<ReserveSourceKind>("manual");
  const [adjustmentId, setAdjustmentId] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setError("");
    try {
      const [claimData, userData, reserveData, supportData, adjustmentData] = await Promise.all([
        getClaim(id),
        getCurrentUser(),
        getAuthoritativeReserveHistory(id),
        getSeverityReserve(id),
        listMatureAdjustments(id),
      ]);
      setClaim(claimData);
      setUser(userData);
      setHistory(reserveData);
      setSupport(supportData.snapshot);
      setAdjustments(adjustmentData.items);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Authoritative reserve workspace could not be loaded.", "محیط ذخیره معتبر بارگذاری نشد."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [id]);

  const canWrite = user?.role === "admin" || user?.role === "claims_manager";
  const currentAdjustments = useMemo(
    () => adjustments.filter((row) => row.status === "approved" && row.source_state_status === "current" && row.currency === claim?.currency),
    [adjustments, claim?.currency],
  );
  const reserveSupport = support?.evaluations.find((row) => row.kind === "reserve") ?? null;
  const selectedAdjustment = currentAdjustments.find((row) => row.id === adjustmentId) ?? null;

  useEffect(() => {
    if (sourceKind === "adjustment" && !adjustmentId && currentAdjustments.length) {
      setAdjustmentId(currentAdjustments[0].id);
    }
  }, [sourceKind, adjustmentId, currentAdjustments]);

  async function refreshSupport() {
    setBusy(true); setError(""); setMessage("");
    try {
      const next = await buildSeverityReserve(id);
      setSupport(next);
      setMessage(r(`Advisory support v${next.snapshot_version} refreshed. No reserve was changed.`, `پشتیبانی مشورتی v${next.snapshot_version} به‌روزرسانی شد. هیچ ذخیره‌ای تغییر نکرد.`));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : r("Reserve Support could not be refreshed.", "پشتیبانی ذخیره به‌روزرسانی نشد."));
    } finally { setBusy(false); }
  }

  async function submit() {
    if (!history || !claim) return;
    if (!amount || Number(amount) < 0) {
      setError(r("Enter the human-authorized reserve amount.", "مبلغ ذخیره تأییدشده توسط انسان را وارد کنید."));
      return;
    }
    if (reason.trim().length < 3) {
      setError(r("Record the human reserve rationale.", "مبنای انسانی تعیین ذخیره را ثبت کنید."));
      return;
    }
    const sourceReference = sourceKind === "reserve_support"
      ? support?.id ?? null
      : sourceKind === "adjustment"
        ? adjustmentId || null
        : null;
    if (sourceKind !== "manual" && !sourceReference) {
      setError(r("Select or refresh a current source before recording this reserve.", "پیش از ثبت ذخیره، منبع جاری را انتخاب یا به‌روزرسانی کنید."));
      return;
    }

    setBusy(true); setError(""); setMessage("");
    try {
      await recordAuthoritativeReserve(id, {
        amount,
        reason: reason.trim(),
        idempotency_key: idempotencyKey,
        expected_reserve_version: history.current_version,
        expected_reserve_hash: history.current_hash,
        source_kind: sourceKind,
        source_reference_id: sourceReference,
      });
      setMessage(r("Authoritative reserve recorded by human action. Upstream context did not set the amount.", "ذخیره معتبر با اقدام انسانی ثبت شد. زمینه بالادستی مبلغ را تعیین نکرد."));
      setAmount(""); setReason(""); setIdempotencyKey(newIdempotencyKey());
      await load();
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : r("Reserve could not be recorded.", "ذخیره ثبت نشد.");
      setError(detail);
      if (e instanceof ApiError && e.status === 409) await load();
    } finally { setBusy(false); }
  }

  if (loading) return <div className="py-20 text-center text-sm text-slate-500">{r("Loading authoritative reserve…", "در حال بارگذاری ذخیره معتبر…")}</div>;
  if (!claim || !history) return <div className="panel p-6 text-sm text-red-700">{error || r("Claim unavailable.", "پرونده در دسترس نیست.")}</div>;

  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Link href={`/claims/${id}/severity-reserve`} className="text-sm font-semibold text-slate-500 hover:text-slate-800">{r("← Back to Severity & Reserve Support", "→ بازگشت به پشتیبانی شدت و ذخیره")}</Link>
      <Link href={`/claims/${id}/adjustment`} className="text-sm font-semibold text-cyan-700 hover:text-cyan-900">{r("Open Adjustment →", "← باز کردن Adjustment")}</Link>
    </div>

    <div>
      <p className="eyebrow"><span dir="ltr">{claim.claim_reference} · Phase 13.6C</span></p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{r("Authoritative Reserve", "ذخیره معتبر")}</h1>
      <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">{r(
        "Only an authorized human can change the claim reserve. Reserve Support and approved current Adjustment may be recorded as provenance, but neither can populate or change the amount automatically.",
        "فقط کاربر انسانی مجاز می‌تواند ذخیره پرونده را تغییر دهد. پشتیبانی ذخیره و Adjustment جاری و تأییدشده می‌توانند به‌عنوان منشأ ثبت شوند، اما هیچ‌کدام حق ندارند مبلغ را خودکار وارد یا تغییر دهند.",
      )}</p>
    </div>

    {error ? <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" dir="auto">{error}</div> : null}
    {message ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800" dir="auto">{message}</div> : null}

    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="panel p-5"><p className="metric-label">{r("Current authoritative reserve", "ذخیره معتبر فعلی")}</p><p className="metric-value text-xl" dir="ltr">{history.current_reserve === null ? r("Not recorded", "ثبت نشده") : formatMoney(history.current_reserve, history.currency)}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("Lineage version", "نسخه زنجیره")}</p><p className="metric-value text-xl" dir="ltr">v{history.current_version}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("Current hash", "هش فعلی")}</p><p className="mt-2 font-mono text-xs text-slate-700" dir="ltr">{shortHash(history.current_hash)}</p></div>
      <div className="panel p-5"><p className="metric-label">{r("History entries", "سوابق ذخیره")}</p><p className="metric-value text-xl" dir="ltr">{history.items.length}</p></div>
    </section>

    <section className="panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="section-title">{r("Record a deliberate reserve change", "ثبت تغییر آگاهانه ذخیره")}</h2><p className="section-subtitle">{r("The amount is always typed by the authorized reviewer. Context cards are read-only provenance.", "مبلغ همیشه توسط بازبین مجاز وارد می‌شود. کارت‌های زمینه فقط منشأ خواندنی هستند.")}</p></div>
        {!canWrite ? <span className="rounded-full bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800">{r("Manager/Admin required", "نیازمند Manager/Admin")}</span> : null}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <button type="button" onClick={() => setSourceKind("manual")} className={`rounded-xl border p-4 text-left ${sourceKind === "manual" ? "border-cyan-400 bg-cyan-50" : "border-slate-200"}`}><p className="font-semibold text-slate-950">{r("Manual human basis", "مبنای دستی انسانی")}</p><p className="mt-1 text-xs leading-5 text-slate-500">{r("No upstream financial source selected.", "هیچ منبع مالی بالادستی انتخاب نشده است.")}</p></button>
        <button type="button" onClick={() => setSourceKind("reserve_support")} className={`rounded-xl border p-4 text-left ${sourceKind === "reserve_support" ? "border-cyan-400 bg-cyan-50" : "border-slate-200"}`}><p className="font-semibold text-slate-950">{r("Reserve Support provenance", "منشأ پشتیبانی ذخیره")}</p><p className="mt-1 text-xs leading-5 text-slate-500">{support ? `v${support.snapshot_version} · ${shortHash(support.source_state_hash)}` : r("No support snapshot", "بدون نسخه پشتیبانی")}</p></button>
        <button type="button" onClick={() => setSourceKind("adjustment")} className={`rounded-xl border p-4 text-left ${sourceKind === "adjustment" ? "border-cyan-400 bg-cyan-50" : "border-slate-200"}`}><p className="font-semibold text-slate-950">{r("Approved Adjustment provenance", "منشأ Adjustment تأییدشده")}</p><p className="mt-1 text-xs leading-5 text-slate-500">{r(`${currentAdjustments.length} current approved version(s)`, `${currentAdjustments.length} نسخه جاری و تأییدشده`)}</p></button>
      </div>

      {sourceKind === "reserve_support" ? <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold text-amber-950">{r("Advisory context only", "فقط زمینه مشورتی")}</p><p className="mt-1 text-xs text-amber-800" dir="ltr">{reserveSupport?.status === "triggered" ? `${formatMoney(String(reserveSupport.lower_amount), history.currency)} – ${formatMoney(String(reserveSupport.upper_amount), history.currency)}` : r("No calculated current range", "بازه جاری محاسبه نشده")}</p></div><button onClick={refreshSupport} disabled={busy} className="secondary-button text-xs">{r("Refresh support", "به‌روزرسانی پشتیبانی")}</button></div></div> : null}

      {sourceKind === "adjustment" ? <div className="mt-4"><label><span className="label">{r("Current approved Adjustment", "Adjustment جاری و تأییدشده")}</span><select className="field" value={adjustmentId} onChange={(e) => setAdjustmentId(e.target.value)}>{!currentAdjustments.length ? <option value="">{r("No current approved Adjustment", "Adjustment جاری و تأییدشده موجود نیست")}</option> : currentAdjustments.map((row) => <option key={row.id} value={row.id}>v{row.version} · {row.title} · {formatMoney(row.net_adjusted, row.currency)}</option>)}</select></label>{selectedAdjustment ? <p className="mt-2 text-xs text-slate-500">{r("Adjustment total is context only and is never copied into the reserve amount.", "جمع Adjustment فقط زمینه است و هرگز در مبلغ ذخیره کپی نمی‌شود.")}</p> : null}</div> : null}

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <label><span className="label">{r("Authoritative reserve amount", "مبلغ ذخیره معتبر")}</span><input aria-label="Authoritative reserve amount" className="field" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={r("Enter manually", "به‌صورت دستی وارد کنید")} disabled={!canWrite || busy} /></label>
        <label><span className="label">{r("Human rationale", "مبنای انسانی")}</span><input aria-label="Human reserve rationale" className="field" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={r("Why is this reserve being set?", "چرا این ذخیره تعیین می‌شود؟")} disabled={!canWrite || busy} /></label>
      </div>
      <p className="mt-3 text-xs text-slate-500">{r(`Concurrency token: v${history.current_version} · ${shortHash(history.current_hash)}`, `توکن همزمانی: v${history.current_version} · ${shortHash(history.current_hash)}`)}</p>
      <button onClick={submit} disabled={!canWrite || busy} className="primary-button mt-4 disabled:opacity-40">{busy ? r("Working…", "در حال انجام…") : r("Record authoritative reserve", "ثبت ذخیره معتبر")}</button>
    </section>

    <section className="panel p-6">
      <h2 className="section-title">{r("Immutable reserve history", "تاریخچه تغییرناپذیر ذخیره")}</h2>
      <p className="section-subtitle">{r("Historical entries remain authoritative records of what was set at that time; later evidence never rewrites them.", "سوابق تاریخی ثبت معتبرِ ذخیره در زمان خود باقی می‌مانند و شواهد بعدی هرگز آن‌ها را بازنویسی نمی‌کنند.")}</p>
      <div className="mt-4 space-y-3">
        {!history.items.length ? <p className="text-sm text-slate-500">{r("No reserve history yet.", "هنوز سابقه ذخیره‌ای ثبت نشده است.")}</p> : history.items.map((row) => <article key={row.id} className="rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-slate-950" dir="ltr">{formatMoney(row.amount, row.currency)}</p><p className="mt-1 text-xs text-slate-500" dir="auto">{row.reason}</p></div><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600" dir="ltr">{row.sequence === null ? "legacy_unbound" : `v${row.sequence}`}</span></div>
          <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2 lg:grid-cols-4"><p>{r("Source", "منشأ")}: <span dir="ltr">{row.source_kind}</span></p><p>{r("Hash", "هش")}: <span className="font-mono" dir="ltr">{shortHash(row.reserve_hash)}</span></p><p>{r("Previous", "قبلی")}: <span className="font-mono" dir="ltr">{shortHash(row.previous_reserve_hash)}</span></p><p dir="ltr">{new Date(row.created_at).toLocaleString(locale === "fa" ? "fa-IR" : "en-GB")}</p></div>
        </article>)}
      </div>
    </section>
  </div>;
}
