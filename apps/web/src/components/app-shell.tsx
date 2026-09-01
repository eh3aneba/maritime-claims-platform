"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LanguageSwitcher } from "@/components/language-switcher";
import { useLocale } from "@/components/locale-provider";
import { ApiError, getCurrentUser, logout } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18n";
import type { CurrentUser } from "@/lib/types";

const nav: Array<{ href: string; labelKey: TranslationKey; mark: string }> = [
  { href: "/dashboard", labelKey: "nav.dashboard", mark: "D" },
  { href: "/claims", labelKey: "nav.claims", mark: "C" },
  { href: "/claims-workbench", labelKey: "nav.claimsWorkbench", mark: "12J" },
  { href: "/ai-review", labelKey: "nav.aiReview", mark: "AI" },
  { href: "/ai-governance", labelKey: "nav.aiGovernance", mark: "G" },
  { href: "/ai-evaluation", labelKey: "nav.aiEvaluation", mark: "E" },
  { href: "/ai-private-pilot", labelKey: "nav.aiPrivatePilot", mark: "11C" },
  { href: "/ai-pilot-outcomes", labelKey: "nav.aiPilotOutcomes", mark: "11D" },
  { href: "/ai-limited-production", labelKey: "nav.aiLimitedProduction", mark: "11E" },
  { href: "/ai-limited-production-outcomes", labelKey: "nav.aiGraduationGate", mark: "11F" },
  { href: "/ai-scale-up", labelKey: "nav.aiControlledScaleUp", mark: "11G" },
  { href: "/ai-scale-up-outcomes", labelKey: "nav.aiReadinessGate", mark: "11H" },
  { href: "/ai-broader-production", labelKey: "nav.aiBroaderProduction", mark: "11I" },
  { href: "/ai-broader-production-outcomes", labelKey: "nav.aiOver50Readiness", mark: "11J" },
  { href: "/ai-high-coverage", labelKey: "nav.aiHighCoverage", mark: "11K" },
  { href: "/ai-high-coverage-outcomes", labelKey: "nav.aiFinalReadiness", mark: "11L" },
  { href: "/ai-final-production-readiness", labelKey: "nav.aiProductionReview", mark: "11M" },
  { href: "/ai-final-production", labelKey: "nav.aiFinalCohort", mark: "11N" },
  { href: "/ai-final-production-outcomes", labelKey: "nav.aiOver90Readiness", mark: "11O" },
  { href: "/ai-near-universal-production", labelKey: "nav.aiNearUniversal", mark: "11P" },
  { href: "/ai-near-universal-outcomes", labelKey: "nav.ai100Readiness", mark: "11Q" },
  { href: "/ai-bounded-full-production", labelKey: "nav.aiBounded100", mark: "11R" },
  { href: "/ai-bounded-full-production-outcomes", labelKey: "nav.aiEnterpriseReadiness", mark: "11S" },
  { href: "/ai-production-wide", labelKey: "nav.aiProductionWide", mark: "11T" },
  { href: "/ai-operations", labelKey: "nav.aiOperations", mark: "12H" },
  { href: "/ai-integrations", labelKey: "nav.aiIntegrations", mark: "12I" },
  { href: "/pilot", labelKey: "nav.pilot", mark: "P" },
  { href: "/outreach", labelKey: "nav.outreach", mark: "O" },
];

const roleKeys: Record<string, TranslationKey> = {
  admin: "role.admin",
  claims_manager: "role.claims_manager",
  claims_handler: "role.claims_handler",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { direction, t } = useLocale();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) router.replace("/login");
      })
      .finally(() => setChecking(false));
  }, [router]);

  async function handleLogout() {
    try { await logout(); }
    finally { router.replace("/login"); router.refresh(); }
  }

  if (checking) {
    return <div className="grid min-h-screen place-items-center bg-slate-50 text-sm text-slate-500">{t("common.loadingSession")}</div>;
  }
  if (!user) return null;

  const roleKey = roleKeys[user.role];
  const roleLabel = roleKey ? t(roleKey) : user.role.replaceAll("_", " ");
  const sidebarSide = direction === "rtl" ? "right-0 border-l" : "left-0 border-r";
  const contentOffset = direction === "rtl" ? "lg:pr-64" : "lg:pl-64";

  return (
    <div className="min-h-screen bg-[#f5f7f9] text-slate-900">
      <aside className={`fixed inset-y-0 z-20 hidden w-64 border-slate-200 bg-[#0b1f2a] text-white lg:block ${sidebarSide}`}>
        <div className="border-b border-white/10 px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/15 bg-white/10 text-sm font-bold" dir="ltr">MC</div>
            <div>
              <div className="text-sm font-semibold tracking-wide">{t("product.name")}</div>
              <div className="mt-0.5 text-xs text-slate-300">{t("product.subtitle")}</div>
            </div>
          </div>
        </div>
        <nav className="px-3 py-5">
          {nav.map((item) => {
            const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`));
            return (
              <Link key={item.href} href={item.href} className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${active ? "bg-white/12 text-white" : "text-slate-300 hover:bg-white/7 hover:text-white"}`}>
                <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-md text-xs font-bold ${active ? "bg-cyan-400 text-slate-950" : "bg-white/8 text-slate-300"}`} dir="ltr">{item.mark}</span>
                <span>{t(item.labelKey)}</span>
              </Link>
            );
          })}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 p-4">
          <div className="rounded-lg bg-white/6 p-3">
            <div className="truncate text-sm font-medium">{user.full_name}</div>
            <div className="mt-1 truncate text-xs text-slate-400" dir="ltr">{user.email}</div>
            <button onClick={handleLogout} className="mt-3 text-xs font-semibold text-cyan-300 hover:text-cyan-200">{t("common.signOut")}</button>
          </div>
        </div>
      </aside>
      <div className={contentOffset}>
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-5 backdrop-blur md:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{t("shell.secureWorkspace")}</p>
          <div className="flex items-center gap-3">
            <LanguageSwitcher compact />
            <span className="hidden text-sm text-slate-500 sm:inline">{roleLabel}</span>
            <div className="grid h-9 w-9 place-items-center rounded-full bg-slate-900 text-xs font-bold text-white" dir="ltr">{user.full_name.split(" ").slice(0, 2).map((part) => part[0]).join("").toUpperCase()}</div>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] px-5 py-7 md:px-8">{children}</main>
      </div>
    </div>
  );
}
