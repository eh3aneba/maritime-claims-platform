import type { NextConfig } from "next";

const aiOperationsLegacyRoutes = [
  "/ai-private-pilot",
  "/ai-limited-production",
  "/ai-scale-up",
  "/ai-broader-production",
  "/ai-high-coverage",
  "/ai-final-production",
  "/ai-near-universal-production",
  "/ai-bounded-full-production",
  "/ai-production-wide",
];

const aiEvaluationLegacyRoutes = [
  "/ai-pilot-outcomes",
  "/ai-limited-production-outcomes",
  "/ai-scale-up-outcomes",
  "/ai-broader-production-outcomes",
  "/ai-high-coverage-outcomes",
  "/ai-final-production-readiness",
  "/ai-final-production-outcomes",
  "/ai-near-universal-outcomes",
  "/ai-bounded-full-production-outcomes",
];

const nextConfig: NextConfig = {
  output: "standalone",
  async redirects() {
    return [
      ...aiOperationsLegacyRoutes.map((source) => ({
        source,
        destination: "/ai-operations",
        permanent: false,
      })),
      ...aiEvaluationLegacyRoutes.map((source) => ({
        source,
        destination: "/ai-evaluation",
        permanent: false,
      })),
    ];
  },
};

export default nextConfig;
