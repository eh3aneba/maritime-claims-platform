export default function Loading() {
  return (
    <div className="space-y-5" aria-live="polite" aria-busy="true">
      <div className="h-5 w-36 animate-pulse rounded bg-slate-200" />
      <div className="h-10 w-72 animate-pulse rounded bg-slate-200" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => <div key={index} className="panel h-28 animate-pulse bg-slate-100" />)}
      </div>
      <div className="panel h-72 animate-pulse bg-slate-100" />
    </div>
  );
}
