"use client";

import { useParams } from "next/navigation";

import DomainClassificationPanel from "./domain-classification-panel";
import EvidenceSearchBridge from "./evidence-search-bridge";
import IntelligenceCore from "./intelligence-core";
import SeverityReserveProxy from "./severity-reserve-proxy";

export default function ClaimIntelligencePage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-7">
      <IntelligenceCore />
      <DomainClassificationPanel claimId={id} />
      <EvidenceSearchBridge claimId={id} />
      <SeverityReserveProxy claimId={id} />
    </div>
  );
}
