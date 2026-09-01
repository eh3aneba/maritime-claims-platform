"use client";

import { useParams } from "next/navigation";

import IntelligenceCore from "./intelligence-core";
import SeverityReserveProxy from "./severity-reserve-proxy";

export default function ClaimIntelligencePage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-7">
      <IntelligenceCore />
      <SeverityReserveProxy claimId={id} />
    </div>
  );
}
