import Link from "next/link";

export default function NotFound() {
  return <main className="grid min-h-screen place-items-center bg-slate-50 p-6"><section className="panel max-w-lg p-8 text-center"><p className="eyebrow">404</p><h1 className="mt-2 text-2xl font-semibold text-slate-950">The requested view was not found</h1><p className="mt-3 text-sm text-slate-500">The claim may be unavailable in your organization, removed, or the link may be incorrect.</p><Link href="/dashboard" className="primary-button mt-6">Return to dashboard</Link></section></main>;
}
