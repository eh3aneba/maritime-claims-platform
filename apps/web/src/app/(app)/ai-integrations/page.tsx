"use client";

import { useCallback, useEffect, useState } from "react";

import { useLocale } from "@/components/locale-provider";
import { API_BASE, ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { aiBoolean, aiLabel, aiT } from "@/lib/i18n-ai-operator";

type Destination = {
  id: string; organization_id: string; name: string; endpoint_url: string; enabled: boolean;
  event_types: string[]; secret_version: number; secret_reference: string; rotated_at: string | null;
  previous_secret_valid_until: string | null; last_tested_at: string | null; last_test_status: string | null;
  created_at: string; updated_at: string; secret_material_persisted: boolean;
};
type Delivery = {
  id: string; destination_id: string; source_workflow_type: string; source_event_id: string;
  source_revision_hash: string; event_type: string; envelope_version: string; occurred_at: string;
  payload_hash: string; secret_version: number; status: string; attempt_count: number; max_attempts: number;
  manual_retry_count: number; next_attempt_at: string; last_attempt_at: string | null;
  delivered_at: string | null; last_http_status: number | null; last_error_code: string | null;
  created_at: string; updated_at: string; content_free: boolean;
};
type Dashboard = {
  metrics: {
    destination_count: number; enabled_destination_count: number; queued_count: number;
    attempting_count: number; failed_count: number; delivered_count: number; dead_letter_count: number;
    delivery_success_bps: number | null;
  };
  destinations: Destination[]; recent_deliveries: Delivery[];
  content_free_outbound_only: boolean; inbound_commands_enabled: boolean;
  raw_claim_or_model_content_exposed: boolean;
};
type SecretIssued = {
  destination: Destination; signing_secret: string; secret_version: number; secret_reference: string;
  disclosure: string;
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—";
}

export default function AIIntegrationsPage() {
  const { locale } = useLocale();
  const L = (en: string, fa: string) => aiT(locale, en, fa);
  // These editable destination values are content, not UI copy. Locale changes intentionally never rewrite them.
  const [data, setData] = useState<Dashboard | null>(null);
  const [name, setName] = useState("Primary SIEM");
  const [endpoint, setEndpoint] = useState("https://example.com/mcri-governance");
  const [documentEvents, setDocumentEvents] = useState(true);
  const [qaEvents, setQaEvents] = useState(true);
  const [enableNew, setEnableNew] = useState(false);
  const [secret, setSecret] = useState<SecretIssued | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const dashboard = await request<Dashboard>("/governance-webhooks");
      setData(dashboard); setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : aiT(locale, "Could not load AI Integrations.", "یکپارچه‌سازی‌های AI بارگذاری نشد."));
    }
  }, [locale]);

  useEffect(() => { void load(); }, [load]);

  function selectedEventTypes() {
    const values: string[] = [];
    if (documentEvents) values.push("ai_operations.document_processing");
    if (qaEvents) values.push("ai_operations.claim_qa_synthesis");
    return values;
  }

  async function createDestination() {
    setBusy("create"); setError(null); setMessage(null); setSecret(null);
    try {
      const issued = await request<SecretIssued>("/governance-webhooks/destinations", {
        method: "POST",
        body: JSON.stringify({ name, endpoint_url: endpoint, event_types: selectedEventTypes(), enabled: enableNew }),
      });
      setSecret(issued);
      setMessage(L("Destination created. Store the signing secret now; the platform will not show it again.", "مقصد ایجاد شد. secret امضا را همین حالا ذخیره کنید؛ پلتفرم دوباره آن را نمایش نمی‌دهد."));
      await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Destination creation failed.", "ایجاد مقصد ناموفق بود.")); }
    finally { setBusy(null); }
  }

  async function toggleDestination(destination: Destination) {
    setBusy(`toggle-${destination.id}`); setError(null); setMessage(null);
    try {
      await request(`/governance-webhooks/destinations/${destination.id}`, {
        method: "PATCH", body: JSON.stringify({ enabled: !destination.enabled }),
      });
      setMessage(L(`${destination.name} ${destination.enabled ? "disabled" : "enabled"}.`, `${destination.name} ${destination.enabled ? "غیرفعال" : "فعال"} شد.`)); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Destination update failed.", "به‌روزرسانی مقصد ناموفق بود.")); }
    finally { setBusy(null); }
  }

  async function rotate(destination: Destination) {
    setBusy(`rotate-${destination.id}`); setError(null); setMessage(null); setSecret(null);
    try {
      const issued = await request<SecretIssued>(`/governance-webhooks/destinations/${destination.id}/rotate-secret`, { method: "POST" });
      setSecret(issued);
      setMessage(L("Signing key rotated. Store the new secret now; the previous key remains valid only for the bounded transition window.", "کلید امضا چرخش یافت. secret جدید را اکنون ذخیره کنید؛ کلید قبلی فقط در بازه گذار محدود معتبر می‌ماند."));
      await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Secret rotation failed.", "چرخش secret ناموفق بود.")); }
    finally { setBusy(null); }
  }

  async function testDestination(destination: Destination) {
    setBusy(`test-${destination.id}`); setError(null); setMessage(null);
    try {
      await request(`/governance-webhooks/destinations/${destination.id}/test`, { method: "POST" });
      setMessage(L("Synthetic content-free test delivery queued.", "تحویل آزمایشی مصنوعی و بدون محتوای خام در صف قرار گرفت.")); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Test delivery failed.", "تحویل آزمایشی ناموفق بود.")); }
    finally { setBusy(null); }
  }

  async function retry(delivery: Delivery) {
    setBusy(`retry-${delivery.id}`); setError(null); setMessage(null);
    try {
      await request(`/governance-webhooks/deliveries/${delivery.id}/retry`, { method: "POST" });
      setMessage(L("Explicit human retry queued.", "تلاش مجدد صریح انسانی در صف قرار گرفت.")); await load();
    } catch (err) { setError(err instanceof ApiError ? err.detail : L("Retry failed.", "تلاش مجدد ناموفق بود.")); }
    finally { setBusy(null); }
  }

  const metrics = data?.metrics;
  return <div className="space-y-7">
    <section className="rounded-2xl bg-[#0b1f2a] p-7 text-white shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">{L("Phase 12I · Content-free outbound governance", "Phase 12I · حاکمیت خروجی بدون محتوای خام")}</p>
      <h1 className="mt-3 text-3xl font-semibold">{L("AI Integrations / SIEM Webhooks", "یکپارچه‌سازی‌های AI / وب‌هوک‌های SIEM")}</h1>
      <p className="mt-3 max-w-5xl text-sm leading-6 text-slate-300">{L("Deliver selected AI Operations governance events to enterprise systems using signed, replay-resistant webhooks. This plane is outbound-only and content-free: no raw claim text, prompts, questions, evidence passages, provider responses or synthesized answers are exposed, and no inbound command can change claim or AI authority.", "رویدادهای منتخب حاکمیتی AI Operations را با وب‌هوک‌های امضاشده و مقاوم در برابر replay به سامانه‌های سازمانی ارسال می‌کند. این مسیر فقط خروجی و بدون محتوای خام است: متن خام پرونده، پرامپت، سؤال، بخش‌های شواهد، پاسخ ارائه‌دهنده یا پاسخ ترکیب‌شده افشا نمی‌شود و هیچ فرمان ورودی نمی‌تواند اختیار پرونده یا AI را تغییر دهد.")}</p>
    </section>

    <div className="rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-3 text-sm text-cyan-950">
      <strong>{L("Security boundary:", "مرز امنیتی:")}</strong> <span dir="ltr">HTTPS · HMAC-SHA256 · idempotency IDs</span> · {L("public-network destinations only · bounded retry/dead-letter · no redirects · no inbound remediation.", "فقط مقصدهای شبکه عمومی · تلاش مجدد/صف بن‌بست محدود · بدون redirect · بدون remediation ورودی.")}
    </div>

    {(message || error) && <div dir="auto" className={`rounded-xl border px-4 py-3 text-sm ${error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error ?? message}</div>}

    {secret && <section className="rounded-2xl border-2 border-amber-300 bg-amber-50 p-5 shadow-sm">
      <p className="text-xs font-bold uppercase tracking-wide text-amber-800">{L("One-time signing secret", "secret یک‌بارمصرف امضا")}</p>
      <p className="mt-2 text-sm text-amber-950">{L("Store this secret in the receiving SIEM/webhook system now. Raw secret material is not persisted and this value will not appear in destination reads.", "این secret را اکنون در سامانه SIEM/webhook مقصد ذخیره کنید. ماده خام secret در پلتفرم نگه‌داری نمی‌شود و این مقدار در خواندن‌های بعدی مقصد نمایش داده نخواهد شد.")}</p>
      <div className="mt-3 break-all rounded-lg bg-white p-3 font-mono text-sm" dir="ltr">{secret.signing_secret}</div>
      <p className="mt-2 text-xs text-amber-800" dir="ltr">Version {secret.secret_version} · {secret.secret_reference}</p>
    </section>}

    <section className="grid gap-4 md:grid-cols-4 xl:grid-cols-7">
      {[
        [L("Destinations", "مقصدها"), metrics?.destination_count ?? 0], [L("Enabled", "فعال"), metrics?.enabled_destination_count ?? 0],
        [L("Queued", "در صف"), metrics?.queued_count ?? 0], [L("Attempting", "در حال تلاش"), metrics?.attempting_count ?? 0],
        [L("Failed", "ناموفق"), metrics?.failed_count ?? 0], [L("Delivered", "تحویل‌شده"), metrics?.delivered_count ?? 0],
        [L("Dead-letter", "صف بن‌بست"), metrics?.dead_letter_count ?? 0],
      ].map(([key, value]) => <div key={String(key)} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><p className="text-xs font-semibold uppercase text-slate-500">{key}</p><p className="mt-2 text-2xl font-semibold">{value}</p></div>)}
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="font-semibold">{L("Add signed destination", "افزودن مقصد امضاشده")}</h2>
      <p className="mt-1 text-xs text-slate-500">{L("Admin action. Destination validation fails closed for loopback/private/local targets.", "اقدام Admin. اعتبارسنجی مقصد برای آدرس‌های loopback/private/local به‌صورت fail-closed عمل می‌کند.")}</p>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <label className="text-xs font-semibold text-slate-600">{L("Name", "نام")}<input dir="auto" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" /></label>
        <label className="text-xs font-semibold text-slate-600">{L("HTTPS endpoint", "endpoint HTTPS")}<input dir="ltr" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm font-normal" /></label>
      </div>
      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={documentEvents} onChange={(e) => setDocumentEvents(e.target.checked)} /> {L("Document-processing governance", "حاکمیت پردازش سند")}</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={qaEvents} onChange={(e) => setQaEvents(e.target.checked)} /> {L("Claim Q&A governance", "حاکمیت پرسش‌وپاسخ پرونده")}</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={enableNew} onChange={(e) => setEnableNew(e.target.checked)} /> {L("Enable immediately", "فعال‌سازی فوری")}</label>
      </div>
      <button disabled={busy !== null || selectedEventTypes().length === 0} onClick={() => void createDestination()} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{L("Create destination", "ایجاد مقصد")}</button>
    </section>

    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold">{L("Destinations", "مقصدها")}</h2><p className="mt-1 text-xs text-slate-500">{L("Signing secrets are write-only; only key version/reference metadata remains visible.", "secretهای امضا write-only هستند؛ فقط metadata نسخه/مرجع کلید قابل مشاهده باقی می‌ماند.")}</p></div>
      <div className="divide-y divide-slate-100">{data?.destinations.map((destination) => <div key={destination.id} className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><h3 className="font-semibold" dir="auto">{destination.name}</h3><span className={`rounded-full px-2 py-1 text-xs font-semibold ${destination.enabled ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>{aiLabel(locale, destination.enabled ? "enabled" : "disabled")}</span></div><p className="mt-1 break-all font-mono text-xs text-slate-500" dir="ltr">{destination.endpoint_url}</p></div><div className="flex gap-2"><button disabled={busy !== null} onClick={() => void toggleDestination(destination)} className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold">{destination.enabled ? L("Disable", "غیرفعال کردن") : L("Enable", "فعال کردن")}</button><button disabled={busy !== null} onClick={() => void rotate(destination)} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-semibold text-amber-800">{L("Rotate secret", "چرخش secret")}</button><button disabled={busy !== null} onClick={() => void testDestination(destination)} className="rounded-lg border border-cyan-300 px-3 py-2 text-xs font-semibold text-cyan-800">{L("Test", "آزمایش")}</button></div></div>
        <div className="mt-3 grid gap-2 text-xs md:grid-cols-3"><div><span className="font-semibold text-slate-500">{L("Events", "رویدادها")}</span><p className="mt-1">{destination.event_types.map((eventType) => aiLabel(locale, eventType)).join(" · ")}</p></div><div><span className="font-semibold text-slate-500">{L("Signing lineage", "زنجیره امضا")}</span><p className="mt-1 font-mono" dir="ltr">v{destination.secret_version} · {destination.secret_reference}</p></div><div><span className="font-semibold text-slate-500">{L("Last test", "آخرین آزمایش")}</span><p className="mt-1">{destination.last_test_status ? aiLabel(locale, destination.last_test_status) : "—"}</p>{destination.last_tested_at ? <p className="mt-1 text-slate-400" dir="ltr">{formatDateTime(destination.last_tested_at, locale)}</p> : null}</div></div>
      </div>)}</div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold">{L("Recent delivery ledger", "دفتر تحویل‌های اخیر")}</h2><p className="mt-1 text-xs text-slate-500">{L("Content-free retry evidence only; response bodies and arbitrary exception text are never stored.", "فقط شواهد تلاش مجدد بدون محتوای خام؛ بدنه پاسخ و متن آزاد exception هرگز ذخیره نمی‌شود.")}</p></div>
      <div className="overflow-x-auto"><table className="min-w-full text-start text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="px-4 py-3">{L("Created", "ایجاد")}</th><th className="px-4 py-3">{L("Event", "رویداد")}</th><th className="px-4 py-3">{L("Status", "وضعیت")}</th><th className="px-4 py-3">{L("Attempts", "تلاش‌ها")}</th><th className="px-4 py-3">{L("HTTP / error", "HTTP / خطا")}</th><th className="px-4 py-3">{L("Payload hash", "Hash payload")}</th><th className="px-4 py-3">{L("Action", "اقدام")}</th></tr></thead><tbody>{data?.recent_deliveries.map((delivery) => <tr key={delivery.id} className="border-t border-slate-100"><td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500" dir="ltr">{formatDateTime(delivery.created_at, locale)}</td><td className="px-4 py-3">{aiLabel(locale, delivery.event_type)}</td><td className="px-4 py-3 font-medium">{aiLabel(locale, delivery.status)}</td><td className="px-4 py-3" dir="ltr">{delivery.attempt_count}/{delivery.max_attempts}{delivery.manual_retry_count ? ` · ${delivery.manual_retry_count} ${L("manual", "دستی")}` : ""}</td><td className="px-4 py-3" dir="ltr">{delivery.last_http_status ?? delivery.last_error_code ?? "—"}</td><td className="px-4 py-3 font-mono text-xs" dir="ltr">{shortHash(delivery.payload_hash)}</td><td className="px-4 py-3">{["failed","dead_letter"].includes(delivery.status) && <button disabled={busy !== null} onClick={() => void retry(delivery)} className="rounded-lg border border-amber-300 px-2 py-1 text-xs font-semibold text-amber-800">{L("Retry", "تلاش مجدد")}</button>}</td></tr>)}</tbody></table></div>
    </section>

    <section className="rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-500">{L("Content-free outbound only", "فقط خروجی بدون محتوای خام")}: {aiBoolean(locale, data?.content_free_outbound_only ?? true)} · {L("inbound commands enabled", "فرمان ورودی فعال")}: {aiBoolean(locale, data?.inbound_commands_enabled ?? false)} · {L("raw claim/model content exposed", "محتوای خام پرونده/مدل افشا شده")}: {aiBoolean(locale, data?.raw_claim_or_model_content_exposed ?? false)}</section>
  </div>;
}
