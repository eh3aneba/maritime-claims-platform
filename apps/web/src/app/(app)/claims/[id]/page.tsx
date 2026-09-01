"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import ClaimOverviewCore from "./overview-core";

export default function ClaimOverviewPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div>
      <div className="mb-4 flex flex-wrap justify-end gap-2">
        <Link
          href={`/claims/${id}/recovery-timebar`}
          className="secondary-button"
        >
          Open Recovery &amp; Time-bar
        </Link>
        <Link
          href={`/claims/${id}/severity-reserve`}
          className="secondary-button"
        >
          Open Severity &amp; Reserve Support
        </Link>
      </div>
      <ClaimOverviewCore />
    </div>
  );
}
