export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") || "https://qantumlearn.academy";

export const MODULE_SLUGS = [
  "nisq-hybrid-workflows",
  "ai-for-quantum-hardware",
  "quantum-enhanced-applications",
  "representation-explainability",
  "industry-use-cases",
  "thermodynamics-roadmap",
];

export const LESSON_SLUGS = [
  "nisq-reality-overview",
  "ai4qc-routing-and-optimization",
  "hybrid-applications-healthcare-vision",
  "representation-language-and-xai",
  "industry-use-cases",
  "thermodynamics-and-roadmap",
];
