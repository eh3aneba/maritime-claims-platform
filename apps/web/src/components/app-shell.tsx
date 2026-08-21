"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getCurrentUser, logout } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";

const nav = [
  { href: "/dashboard", label: "Dashboard", mark: "D" },
  { href: "/claims", label: "Claims", mark: "C" },
  { href: "/ai-review", label: "AI Review", mark: "AI" },
  { href: "/ai-governance", label: "AI Governance", mark: "G" },
  { href: "/ai-evaluation", label: "AI Evaluation", mark: "E" },
  { href: "/ai-private-pilot", label: "AI Private Pilot", mark: "11C" },
  { href: "/ai-pilot-outcomes", label: "AI Pilot Outcomes", mark: "11D" },
  { href: "/ai-limited-production", label: "AI Limited Production", mark: "11E" },
  { href: "/ai-limited-production-outcomes", label: "AI Graduation Gate", mark: "11F" },
  { href: "/ai-scale-up", label: "AI Controlled Scale-Up", mark: "11G" },
  { href: "/ai-scale-up-outcomes", label: "AI Readiness Gate", mark: "11H" },
  { href: "/ai-broader-production", label: "AI Broader Production", mark: "11I" },
  { href: "/ai-broader-production-outcomes", label: "AI >50% Readiness", mark: "11J" },
  { href: "/ai-high-coverage", label: "AI High Coverage", mark: "11K" },
  { href: "/ai-high-coverage-outcomes", label: "AI Final Readiness", mark: "11L" },
  { href: "/ai-final-production-readiness", label: "AI Production Review", mark: "11M" },
  { href: "/pilot", label: "Pilot", mark: "P" },
  { href: "/outreach", label: "Outreach", mark: "O" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
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
    return <div className="grid min-h-screen place-items-center bg-slate-50 text-sm text-slate-500">Checking secure session…</div>;
  }
  if (!user) return null;

  return (
    <div className="min-h-screen bg-[#f5f7f9] text-slate-900">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-slate-200 bg-[#0b1f2a] text-white lg:block">
        <div className="border-b border-white/10 px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-lg border border-white/15 bg-white/10 text-sm font-bold">MC</div>
            <div><div className="text-sm font-semibold tracking-wide">Maritime Claims</div><div className="mt-0.5 text-xs text-slate-300">Risk Intelligence Platform</div></div>
          </div>
        </div>
        <nav className="px-3 py-5">
          {nav.map((item) => {
            const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
            return <Link key={item.href} href={item.href} className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${active ? "bg-white/12 text-white" : "text-slate-300 hover:bg-white/7 hover:text-white"}`}>
              <span className={`grid h-7 w-7 place-items-center rounded-md text-xs font-bold ${active ? "bg-cyan-400 text-slate-950" : "bg-white/8 text-slate-300"}`}>{item.mark}</span>{item.label}
            </Link>;
          })}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 p-4">
          <div className="rounded-lg bg-white/6 p-3">
            <div className="truncate text-sm font-medium">{user.full_name}</div>
            <div className="mt-1 truncate text-xs text-slate-400">{user.email}</div>
            <button onClick={handleLogout} className="mt-3 text-xs font-semibold text-cyan-300 hover:text-cyan-200">Sign out</button>
          </div>
        </div>
      </aside>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-5 backdrop-blur md:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Secure claims workspace</p>
          <div className="flex items-center gap-3"><span className="hidden text-sm text-slate-500 sm:inline">{user.role.replaceAll("_", " ")}</span><div className="grid h-9 w-9 place-items-center rounded-full bg-slate-900 text-xs font-bold text-white">{user.full_name.split(" ").slice(0, 2).map((part) => part[0]).join("").toUpperCase()}</div></div>
        </header>
        <main className="mx-auto max-w-[1500px] px-5 py-7 md:px-8">{children}</main>
      </div>
    </div>
  );
}
