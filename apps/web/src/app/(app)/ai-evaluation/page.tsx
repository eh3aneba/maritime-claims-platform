"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import {
  ApiError, createAIEvaluationSuite, decideAIEvaluationPromotion,
  finalizeAIEvaluationSuite, getAIEvaluation, getAIGovernance,
  recordAIEvaluationCase, reviewAIEvaluationSuite, revokeAIEvaluationPromotion,
} from "@/lib/api";
import { aiBoolean, aiLabel, aiT } from "@/lib/i18n-ai-operator";
import type { AIEvaluationDashboard, AIEvaluationSuite, AIGovernanceDashboard } from "@/lib/types";

type Scenario = "baseline" | "prompt_injection" | "malformed_input" | "cross_tenant" | "restricted_data";
type ReviewRole = "quality" | "risk";
type ReviewDraft = { evidence_reference: string; note: string };
type CaseDraft = {
  case_key: string; document_type: "chief_engineer_report" | "engine_log";
  scenario_type: Scenario; data_mode: "synthetic" | "deidentified"; result: "" | "pass" | "fail";
  field_true_positive: string; field_false_positive: string; field_false_negative: string;
  extracted_claim_count: string; unsupported_claim_count: string;
  source_quote_checked_count: string; source_quote_valid_count: string;
  human_approved_count: string; human_edited_count: string; human_rejected_count: string;
  latency_ms: string; input_tokens: string; output_tokens: string;
  observed_provider_cost_microusd: string; boundary_control_passed: "" | "pass" | "fail";
  evidence_reference: string; note: string;
};

const measuredNumberKeys = [
  "field_true_positive", "field_false_positive", "field_false_negative",
  "extracted_claim_count", "unsupported_claim_count", "source_quote_checked_count",
  "source_quote_valid_count", "human_approved_count", "human_edited_count",
  "human_rejected_count", "latency_ms", "input_tokens", "output_tokens",
  "observed_provider_cost_microusd",
] as const;

const initialCase: CaseDraft = {
  case_key: "", document_type: "chief_engineer_report", scenario_type: "baseline",
  data_mode: "synthetic", result: "", field_true_positive: "",
  field_false_positive: "", field_false_negative: "", extracted_claim_count: "",
  unsupported_claim_count: "", source_quote_checked_count: "", source_quote_valid_count: "",
  human_approved_count: "", human_edited_count: "", human_rejected_count: "",
  latency_ms: "", input_tokens: "", output_tokens: "",
  observed_provider_cost_microusd: "", boundary_control_passed: "",
  evidence_reference: "", note: "",
};
const controlClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-cyan-600 focus:ring-2 focus:ring-cyan-100";

function badge(status: string) {
  if (["review_ready", "promotion_ready", "staging_promoted", "pass"].includes(status)) {
    return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  }
  if (["failed", "review_rejected", "held", "revoked", "fail"].includes(status)) {
    return "bg-rose-50 text-rose-700 ring-rose-200";
  }
  return "bg-amber-50 text-amber-700 ring-amber-200";
}

function Badge({ value }: { value: string }) {
  const { locale } = useLocale();
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${badge(value)}`}>{aiLabel(locale, value)}</span>;
}

function metric(item: AIEvaluationSuite, key: string) {
  const value = item.metrics?.[key];
  return typeof value === "number" ? value : null;
}

function percent(value: number | null) {
  return value === null ? "—" : `${(value / 100).toFixed(2)}%`;
}

export default function AIEvaluationPage() {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => aiT(locale, en, fa);
  const [evaluation, setEvaluation] = useState<AIEvaluationDashboard | null>(null);
  const [governance, setGovernance] = useState<AIGovernanceDashboard | null>(null);
  const [draft, setDraft] = useState<CaseDraft>(initialCase);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [evaluationData, governanceData] = await Promise.all([getAIEvaluation(), getAIGovernance()]);
      setEvaluation(evaluationData); setGovernance(governanceData); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : aiT(locale, "Could not load the AI evaluation gate.", "دروازه ارزیابی AI بارگذاری نشد."));
    }
  }, [locale]);
  useEffect(() => { void load(); }, [load]);

  const activeActivation = governance?.activation_requests.find((item) => item.summary.authorization_active) ?? null;
  const latest = evaluation?.suites[0] ?? null;
  const canCreate = !latest || ["failed", "review_rejected", "held", "revoked"].includes(latest.status)
    || (latest.status === "staging_promoted" && latest.promotion_expires_at !== null
      && new Date(latest.promotion_expires_at).getTime() <= Date.now());

  async function run(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key); setMessage(null); setError(null);
    try { await action(); setMessage(success); await load(); }
    catch (err) { setError(err instanceof ApiError ? err.detail : L("The evaluation action failed.", "عملیات ارزیابی ناموفق بود.")); }
    finally { setBusy(null); }
  }

  async function createSuite() {
    if (!activeActivation) { setError(L("An active Sprint 11A staging authorization is required.", "یک مجوز فعال محیط آزمایشی از Sprint 11A لازم است.")); return; }
    await run("create", () => createAIEvaluationSuite(activeActivation.id),
      L("A content-free, version-pinned evaluation suite was created.", "یک مجموعه ارزیابی بدون محتوای خام و مقید به نسخه ایجاد شد."));
  }

  async function submitCase(event: FormEvent) {
    event.preventDefault();
    if (!latest || latest.status !== "collecting") return;
    if (!draft.result || !draft.boundary_control_passed
        || measuredNumberKeys.some((key) => draft[key].trim() === "")
        || !draft.evidence_reference.trim() || draft.note.trim().length < 10) {
      setError(L(
        "Enter every measured value, the measured result, the boundary-control outcome, a bounded evidence reference, and a human verification note before recording this case.",
        "پیش از ثبت این مورد، همه مقادیر اندازه‌گیری‌شده، نتیجه، وضعیت کنترل مرزی، مرجع شواهد محدود و یادداشت بررسی انسانی را وارد کنید.",
      ));
      return;
    }
    const payload = {
      case_key: draft.case_key,
      document_type: draft.document_type,
      scenario_type: draft.scenario_type,
      data_mode: draft.data_mode,
      result: draft.result,
      field_true_positive: Number(draft.field_true_positive),
      field_false_positive: Number(draft.field_false_positive),
      field_false_negative: Number(draft.field_false_negative),
      extracted_claim_count: Number(draft.extracted_claim_count),
      unsupported_claim_count: Number(draft.unsupported_claim_count),
      source_quote_checked_count: Number(draft.source_quote_checked_count),
      source_quote_valid_count: Number(draft.source_quote_valid_count),
      human_approved_count: Number(draft.human_approved_count),
      human_edited_count: Number(draft.human_edited_count),
      human_rejected_count: Number(draft.human_rejected_count),
      latency_ms: Number(draft.latency_ms),
      input_tokens: Number(draft.input_tokens),
      output_tokens: Number(draft.output_tokens),
      observed_provider_cost_microusd: Number(draft.observed_provider_cost_microusd),
      boundary_control_passed: draft.boundary_control_passed === "pass",
      evidence_reference: draft.evidence_reference.trim(),
      note: draft.note.trim(),
    };
    await run("case", () => recordAIEvaluationCase(latest.id, payload),
      L("Observed aggregate benchmark result recorded without prompt, document or model response content.", "نتیجه تجمیعی مشاهده‌شده بدون ذخیره متن پرامپت، سند یا پاسخ مدل ثبت شد."));
    setDraft((current) => ({ ...initialCase,
      document_type: current.document_type === "chief_engineer_report" ? "engine_log" : "chief_engineer_report" }));
  }

  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">{L("Sprint 11B · measured promotion", "Sprint 11B · ارتقای مبتنی بر سنجش")}</p>
      <h1 className="mt-3 text-3xl font-semibold">{L("AI quality, safety and cost evaluation", "ارزیابی کیفیت، ایمنی و هزینه AI")}</h1>
      <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">{L("Promotion is fail-closed and pinned to the Sprint 11A model, prompt and schema bundle. This ledger stores only aggregate observations and hashes—never document text, prompts, expected answers, provider responses or keys.", "ارتقا به‌صورت fail-closed و مقید به مدل، پرامپت و بسته schema در Sprint 11A است. این دفتر فقط مشاهدات تجمیعی و hashها را نگه می‌دارد و هرگز متن سند، پرامپت، پاسخ مورد انتظار، پاسخ ارائه‌دهنده یا کلیدها را ذخیره نمی‌کند.")}</p>
    </section>

    {(message || error) && <div role="status" dir="auto" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-50 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    <section className="grid gap-4 md:grid-cols-4">
      {[
        [L("Cases", "موارد"), latest ? `${latest.summary.case_count}/${latest.summary.required_case_count}` : "0/12"],
        [L("Thresholds", "آستانه‌ها"), latest?.summary.thresholds_passed ? L("Passed", "قبول") : L("Not passed", "قبول نشده")],
        [L("Independent reviews", "بازبینی‌های مستقل"), latest?.summary.independent_reviews_complete ? L("Complete", "کامل") : L("Incomplete", "ناقص")],
        [L("Promotion active", "ارتقای فعال"), aiBoolean(locale, Boolean(latest?.summary.promotion_active))],
      ].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-xl font-semibold text-slate-900">{value}</p></div>)}
    </section>

    {canCreate && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">{L("Start a version-pinned evaluation attempt", "شروع ارزیابی مقید به نسخه")}</h2>
      <p className="mt-2 text-sm text-slate-600">{L("Active activation:", "فعال‌سازی فعال:")} {activeActivation ? <span dir="ltr">{activeActivation.model} · {activeActivation.id}</span> : L("none", "هیچ‌کدام")}</p>
      <button disabled={!activeActivation || busy !== null} onClick={() => void createSuite()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{L("Create evaluation suite", "ایجاد مجموعه ارزیابی")}</button>
    </section>}

    {latest && <SuiteSummary item={latest} busy={busy} run={run} />}

    {latest?.status === "collecting" && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{L("Record an observed benchmark result", "ثبت نتیجه مشاهده‌شده benchmark")}</h2><p className="mt-1 text-sm text-slate-600">{L("Every measured field starts blank. Enter only observed aggregate values from the referenced controlled artifact; no sample success values are persisted by default.", "همه فیلدهای سنجش در ابتدا خالی هستند. فقط مقادیر تجمیعی مشاهده‌شده از artifact کنترل‌شده مرجع را وارد کنید؛ هیچ مقدار موفقیت نمونه‌ای به‌صورت پیش‌فرض ثبت نمی‌شود.")}</p></div><Badge value="content_free" /></div>
      <form onSubmit={submitCase} className="mt-5 space-y-4">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label={L("Case key", "کلید مورد")}><input dir="ltr" required value={draft.case_key} onChange={(event) => setDraft({ ...draft, case_key: event.target.value })} className={controlClass} placeholder="ce-baseline-001" /></Field>
          <Field label={L("Document type", "نوع سند")}><select value={draft.document_type} onChange={(event) => setDraft({ ...draft, document_type: event.target.value as CaseDraft["document_type"] })} className={controlClass}><option value="chief_engineer_report">{aiLabel(locale, "chief_engineer_report")}</option><option value="engine_log">{aiLabel(locale, "engine_log")}</option></select></Field>
          <Field label={L("Scenario", "سناریو")}><select value={draft.scenario_type} onChange={(event) => setDraft({ ...draft, scenario_type: event.target.value as Scenario })} className={controlClass}><option value="baseline">{aiLabel(locale, "baseline")}</option><option value="prompt_injection">{aiLabel(locale, "prompt_injection")}</option><option value="malformed_input">{aiLabel(locale, "malformed_input")}</option><option value="cross_tenant">{aiLabel(locale, "cross_tenant")}</option><option value="restricted_data">{aiLabel(locale, "restricted_data")}</option></select></Field>
          <Field label={L("Measured result", "نتیجه اندازه‌گیری‌شده")}><select required value={draft.result} onChange={(event) => setDraft({ ...draft, result: event.target.value as CaseDraft["result"] })} className={controlClass}><option value="">{L("Select result", "انتخاب نتیجه")}</option><option value="pass">{aiLabel(locale, "pass")}</option><option value="fail">{aiLabel(locale, "fail")}</option></select></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            [L("True positive", "مثبت صحیح"), "field_true_positive"], [L("False positive", "مثبت کاذب"), "field_false_positive"],
            [L("False negative", "منفی کاذب"), "field_false_negative"], [L("Extracted claims", "ادعاهای استخراج‌شده"), "extracted_claim_count"],
            [L("Unsupported", "بدون پشتوانه"), "unsupported_claim_count"], [L("Quotes checked", "نقل‌قول‌های بررسی‌شده"), "source_quote_checked_count"],
            [L("Quotes valid", "نقل‌قول‌های معتبر"), "source_quote_valid_count"], [L("Human approved", "تأیید انسانی"), "human_approved_count"],
            [L("Human edited", "ویرایش انسانی"), "human_edited_count"], [L("Human rejected", "رد انسانی"), "human_rejected_count"],
            [L("Latency ms", "تأخیر ms"), "latency_ms"], [L("Input tokens", "توکن ورودی"), "input_tokens"],
            [L("Output tokens", "توکن خروجی"), "output_tokens"], [L("Observed cost µUSD", "هزینه مشاهده‌شده µUSD"), "observed_provider_cost_microusd"],
          ].map(([label, key]) => <NumberField key={key} label={label} value={draft[key as (typeof measuredNumberKeys)[number]]} onChange={(value) => setDraft({ ...draft, [key]: value })} />)}
        </div>
        <div className="grid gap-3 md:grid-cols-3"><Field label={L("Boundary control outcome", "نتیجه کنترل مرزی")}><select required value={draft.boundary_control_passed} onChange={(event) => setDraft({ ...draft, boundary_control_passed: event.target.value as CaseDraft["boundary_control_passed"] })} className={controlClass}><option value="">{L("Select observed outcome", "انتخاب نتیجه مشاهده‌شده")}</option><option value="pass">{L("Passed", "قبول")}</option><option value="fail">{L("Failed", "رد")}</option></select></Field><Field label={L("Bounded evidence reference", "مرجع شواهد محدود")}><input dir="ltr" required value={draft.evidence_reference} onChange={(event) => setDraft({ ...draft, evidence_reference: event.target.value })} className={controlClass} placeholder="artifact://..." /></Field><Field label={L("Human verification note", "یادداشت بررسی انسانی")}><input dir="auto" required minLength={10} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} className={controlClass} placeholder={L("What was actually checked?", "چه چیزی واقعاً بررسی شد؟")} /></Field></div>
        <button disabled={busy !== null} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{L("Record immutable result", "ثبت نتیجه تغییرناپذیر")}</button>
      </form>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">{L("Immutable case ledger", "دفتر تغییرناپذیر موارد")}</h2>
      <div className="mt-4 space-y-2">{latest?.cases.length ? latest.cases.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-medium"><span dir="ltr">{item.case_key}</span> · {aiLabel(locale, item.document_type)}</p><p className="mt-1 text-xs text-slate-500"><span>{aiLabel(locale, item.scenario_type)}</span> · <span dir="ltr">{item.latency_ms} ms · SHA-256 {item.result_hash.slice(0, 12)}…</span></p></div><Badge value={item.result} /></div>) : <p className="text-sm text-slate-500">{L("No benchmark observations recorded.", "هیچ مشاهده benchmark ثبت نشده است.")}</p>}</div>
    </section>
  </div>;
}

function SuiteSummary({ item, busy, run }: { item: AIEvaluationSuite; busy: string | null; run: (key: string, action: () => Promise<unknown>, success: string) => Promise<void> }) {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => aiT(locale, en, fa);
  const roles: ReviewRole[] = ["quality", "risk"];
  const reviewed = useMemo(() => new Set(item.reviews.map((review) => review.review_role)), [item.reviews]);
  const [reviewDrafts, setReviewDrafts] = useState<Record<ReviewRole, ReviewDraft>>({
    quality: { evidence_reference: "", note: "" },
    risk: { evidence_reference: "", note: "" },
  });

  function setReviewDraft(role: ReviewRole, patch: Partial<ReviewDraft>) {
    setReviewDrafts((current) => ({ ...current, [role]: { ...current[role], ...patch } }));
  }

  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{L("Attempt", "تلاش")} <span dir="ltr">{item.attempt_number}</span> · <span dir="auto">{item.benchmark_profile}</span></p><h2 className="mt-1 text-xl font-semibold" dir="ltr">{item.activation_model}</h2><p className="mt-1 text-xs text-slate-500" dir="ltr">Prompt {item.prompt_bundle_version} · Schema {item.schema_bundle_version} · {item.max_input_chars} chars · {item.max_output_tokens} output tokens</p></div><Badge value={item.status} /></div>
    {item.metrics && <div className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">{[
      [L("Precision", "دقت"), percent(metric(item, "precision_bps"))], [L("Recall", "Recall"), percent(metric(item, "recall_bps"))],
      [L("Unsupported", "بدون پشتوانه"), percent(metric(item, "unsupported_claim_rate_bps"))], [L("Quote validity", "اعتبار نقل‌قول"), percent(metric(item, "source_quote_validity_bps"))],
      [L("Override", "تغییر انسانی"), percent(metric(item, "human_override_rate_bps"))], [L("P95 latency", "تأخیر P95"), `${metric(item, "p95_latency_ms") ?? "—"} ms`],
    ].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold" dir="ltr">{value}</p></div>)}</div>}
    {item.failure_reasons.length > 0 && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" dir="auto">{L("Failed controls:", "کنترل‌های ناموفق:")} {item.failure_reasons.join(", ")}</div>}
    <div className="mt-5 border-t border-slate-100 pt-5">
      <button disabled={busy !== null || item.status !== "collecting"} onClick={() => void run("finalize", () => finalizeAIEvaluationSuite(item.id), L("Evaluation finalized; threshold result is now immutable.", "ارزیابی نهایی شد؛ نتیجه آستانه اکنون تغییرناپذیر است."))} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{L("Finalize thresholds", "نهایی‌سازی آستانه‌ها")}</button>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {roles.map((role) => {
          const draft = reviewDrafts[role];
          const alreadyReviewed = reviewed.has(role);
          const reviewOpen = ["review_ready", "promotion_ready"].includes(item.status) && !alreadyReviewed;
          return <div key={role} className="rounded-xl border border-slate-200 p-4">
            <p className="text-sm font-semibold">{aiLabel(locale, role)} · {L("independent review", "بازبینی مستقل")}</p>
            {alreadyReviewed ? <p className="mt-2 text-sm text-slate-500">{L("Review already recorded.", "بازبینی قبلاً ثبت شده است.")}</p> : <>
              <div className="mt-3 space-y-3">
                <Field label={L("Reviewer evidence reference", "مرجع شواهد بازبین")}><input dir="ltr" disabled={!reviewOpen || busy !== null} value={draft.evidence_reference} onChange={(event) => setReviewDraft(role, { evidence_reference: event.target.value })} className={controlClass} placeholder="artifact://..." /></Field>
                <Field label={L("Reviewer note", "یادداشت بازبین")}><textarea dir="auto" disabled={!reviewOpen || busy !== null} minLength={10} value={draft.note} onChange={(event) => setReviewDraft(role, { note: event.target.value })} className={controlClass} placeholder={L("Describe what you independently checked.", "توضیح دهید چه چیزی را مستقلاً بررسی کردید.")} /></Field>
              </div>
              <div className="mt-3 flex gap-2">
                <button disabled={!reviewOpen || busy !== null || !draft.evidence_reference.trim() || draft.note.trim().length < 10} onClick={() => void run(`review-${role}`, () => reviewAIEvaluationSuite(item.id, role, "approve", { evidence_reference: draft.evidence_reference.trim(), note: draft.note.trim() }), L(`${aiLabel(locale, role)} review recorded.`, `بازبینی ${aiLabel(locale, role)} ثبت شد.`))} className="rounded-lg border border-emerald-300 px-3 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-40">{L("Approve with evidence", "تأیید با شواهد")}</button>
                <button disabled={!reviewOpen || busy !== null || draft.note.trim().length < 10} onClick={() => void run(`review-${role}`, () => reviewAIEvaluationSuite(item.id, role, "reject", { evidence_reference: null, note: draft.note.trim() }), L(`${aiLabel(locale, role)} review rejected.`, `بازبینی ${aiLabel(locale, role)} رد شد.`))} className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">{L("Reject with note", "رد با یادداشت")}</button>
              </div>
            </>}
          </div>;
        })}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button disabled={busy !== null || item.status !== "promotion_ready"} onClick={() => void run("promote", () => decideAIEvaluationPromotion(item.id, "promote_staging"), L("The evaluated synthetic/de-identified staging bundle was promoted.", "بسته ارزیابی‌شده مصنوعی/ناشناس‌سازی‌شده در محیط آزمایشی ارتقا یافت."))} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{L("Admin promote staging", "ارتقای محیط آزمایشی توسط Admin")}</button>
        <button disabled={busy !== null || item.status !== "promotion_ready"} onClick={() => void run("hold", () => decideAIEvaluationPromotion(item.id, "hold"), L("Promotion held.", "ارتقا متوقف شد."))} className="rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-800 disabled:opacity-40">{L("Admin hold", "توقف توسط Admin")}</button>
        <button disabled={busy !== null || item.status !== "staging_promoted"} onClick={() => void run("revoke", () => revokeAIEvaluationPromotion(item.id), L("Evaluation promotion revoked.", "ارتقای ارزیابی لغو شد."))} className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-40">{L("Revoke promotion", "لغو ارتقا")}</button>
      </div>
    </div>
    <p className="mt-3 text-xs text-slate-500">{L("The requester, Quality reviewer and Risk reviewer must be three different people. Each approving reviewer must enter their own bounded evidence reference and note; only Admin can promote.", "درخواست‌کننده، بازبین کیفیت و بازبین ریسک باید سه نفر متفاوت باشند. هر بازبین تأییدکننده باید مرجع شواهد محدود و یادداشت خودش را وارد کند؛ فقط Admin می‌تواند ارتقا دهد.")}</p>
    {item.evaluation_hash && <p className="mt-3 break-all font-mono text-[10px] text-slate-400" dir="ltr">Evaluation SHA-256: {item.evaluation_hash}</p>}
  </section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1 block text-xs font-semibold text-slate-600">{label}</span>{children}</label>; }
function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <Field label={label}><input dir="ltr" type="number" min={0} required value={value} onChange={(event) => onChange(event.target.value)} className={controlClass} placeholder="—" /></Field>; }
