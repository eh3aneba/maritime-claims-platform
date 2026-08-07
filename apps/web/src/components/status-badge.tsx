import { priorityLabel, statusLabel } from "@/lib/format";
import type { ClaimPriority, ClaimStatus } from "@/lib/types";

const statusClasses: Record<ClaimStatus, string> = {
  new: "bg-slate-100 text-slate-700 ring-slate-200",
  triage: "bg-blue-50 text-blue-700 ring-blue-200",
  awaiting_documents: "bg-amber-50 text-amber-800 ring-amber-200",
  investigation: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  technical_review: "bg-violet-50 text-violet-700 ring-violet-200",
  financial_review: "bg-cyan-50 text-cyan-800 ring-cyan-200",
  coverage_review: "bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200",
  negotiation: "bg-orange-50 text-orange-700 ring-orange-200",
  settlement: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  recovery: "bg-teal-50 text-teal-700 ring-teal-200",
  closed: "bg-slate-100 text-slate-600 ring-slate-200",
  on_hold: "bg-yellow-50 text-yellow-800 ring-yellow-200",
  litigation: "bg-rose-50 text-rose-700 ring-rose-200",
  rejected: "bg-red-50 text-red-700 ring-red-200",
  withdrawn: "bg-zinc-100 text-zinc-700 ring-zinc-200",
};

const priorityClasses: Record<ClaimPriority, string> = {
  low: "text-slate-600",
  medium: "text-amber-700",
  high: "text-orange-700",
  critical: "text-red-700",
};

export function StatusBadge({ status }: { status: ClaimStatus }) {
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${statusClasses[status]}`}>{statusLabel[status]}</span>;
}

export function PriorityText({ priority }: { priority: ClaimPriority }) {
  return <span className={`text-sm font-semibold ${priorityClasses[priority]}`}>{priorityLabel[priority]}</span>;
}
