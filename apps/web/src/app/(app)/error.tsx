"use client";

export default function ErrorState({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <section className="panel mx-auto mt-16 max-w-2xl p-8 text-center">
      <p className="eyebrow">Workspace error</p>
      <h1 className="mt-2 text-2xl font-semibold text-slate-950">This view could not be loaded</h1>
      <p className="mt-3 text-sm leading-6 text-slate-500">Your claim data has not been changed. Retry the request; if the problem continues, check API health and the deployment logs.</p>
      <button onClick={reset} className="primary-button mt-6">Try again</button>
    </section>
  );
}
