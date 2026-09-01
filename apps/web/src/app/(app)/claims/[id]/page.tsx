"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import ClaimOverviewCore from "./overview-core";

export default function ClaimOverviewPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <Link
          href={`/claims/${id}/recovery-timebar`}
          className="secondary-button"
        >
          Open Recovery &amp; Time-bar
        </Link>
      </div>
      <ClaimOverviewCore />
    </div>
  );
}
