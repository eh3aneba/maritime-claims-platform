const milestones = [
  "Authentication foundation",
  "Organization and tenant model",
  "Claim creation",
  "Claim overview",
  "Document upload",
];

export default function Home() {
  return (
    <main className="min-h-screen p-8 md:p-12">
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 flex items-start justify-between gap-6 border-b border-slate-200 pb-6">
          <div>
            <p className="mb-2 text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
              Sprint 2 / Phase B
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-950 md:text-4xl">
              Maritime Claims & Risk Intelligence Platform
            </h1>
            <p className="mt-3 max-w-3xl text-base leading-7 text-slate-600">
              Technical foundation for the H&M Machinery Claims MVP. AI processing is intentionally
              deferred until the secure claim and document foundation is in place.
            </p>
          </div>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-800">
            Foundation online
          </span>
        </div>

        <section className="grid gap-4 md:grid-cols-3">
          <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Frontend</p>
            <p className="mt-1 text-lg font-semibold">Next.js + TypeScript</p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Backend</p>
            <p className="mt-1 text-lg font-semibold">FastAPI + Python</p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Database</p>
            <p className="mt-1 text-lg font-semibold">PostgreSQL 18</p>
          </article>
        </section>

        <section className="mt-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-950">Next technical milestones</h2>
          <ul className="mt-4 space-y-3">
            {milestones.map((milestone, index) => (
              <li key={milestone} className="flex items-center gap-3 text-slate-700">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700">
                  {index + 1}
                </span>
                {milestone}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
