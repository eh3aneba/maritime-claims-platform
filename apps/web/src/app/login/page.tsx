"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { LanguageSwitcher } from "@/components/language-switcher";
import { useLocale } from "@/components/locale-provider";
import { ApiError, login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useLocale();
  const [organization, setOrganization] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login({ organization_slug: organization.trim(), email: email.trim(), password });
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("login.genericError"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="relative grid min-h-screen bg-[#eef2f4] lg:grid-cols-[1.05fr_0.95fr]">
      <div className="absolute top-5 z-10 ltr:right-5 rtl:left-5">
        <LanguageSwitcher />
      </div>
      <section className="hidden bg-[#0b1f2a] p-14 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-white/15 bg-white/10 text-sm font-bold" dir="ltr">MC</div>
          <div>
            <p className="text-sm font-semibold tracking-wide">{t("product.name")}</p>
            <p className="text-xs text-slate-300">{t("product.subtitle")}</p>
          </div>
        </div>
        <div className="max-w-xl pb-12">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">{t("login.mvp")}</p>
          <h1 className="mt-5 text-5xl font-semibold leading-[1.08] tracking-tight">{t("login.hero")}</h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-slate-300">{t("login.description")}</p>
          <div className="mt-10 grid grid-cols-3 gap-3 text-xs text-slate-300">
            {[t("login.tenantIsolated"), t("login.auditReady"), t("login.humanControlled")].map((item) => <div key={item} className="rounded-lg border border-white/10 bg-white/5 px-3 py-3">{item}</div>)}
          </div>
        </div>
        <p className="text-xs text-slate-500">{t("login.privateEnvironment")}</p>
      </section>

      <section className="flex items-center justify-center p-6 md:p-12">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-[0_20px_60px_rgba(15,23,42,0.08)] md:p-9">
          <div className="mb-8 lg:hidden">
            <p className="text-sm font-bold text-slate-900">{t("product.name")}</p>
            <p className="text-xs text-slate-500">{t("product.subtitle")}</p>
          </div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">{t("login.secureAccess")}</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{t("login.heading")}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">{t("login.help")}</p>

          <form onSubmit={submit} className="mt-7 space-y-5">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">{t("login.organization")}</span>
              <input value={organization} onChange={(e) => setOrganization(e.target.value)} required minLength={2} autoComplete="organization" placeholder="demo-marine" className="field" dir="ltr" />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">{t("login.email")}</span>
              <input value={email} onChange={(e) => setEmail(e.target.value)} required type="email" autoComplete="email" placeholder="claims@example.com" className="field" dir="ltr" />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">{t("login.password")}</span>
              <input value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} type="password" autoComplete="current-password" placeholder="••••••••••••" className="field" dir="ltr" />
            </label>
            {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">{error}</div> : null}
            <button disabled={submitting} className="w-full rounded-lg bg-[#0b1f2a] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#123344] disabled:cursor-not-allowed disabled:opacity-60">{submitting ? t("login.signingIn") : t("login.signIn")}</button>
          </form>
        </div>
      </section>
    </main>
  );
}
