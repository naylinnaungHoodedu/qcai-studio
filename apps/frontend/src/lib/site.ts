export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") || "https://qantumlearn.academy";
export const OWNER_NAME = "Nay Linn Aung";
export const CONTACT_EMAIL = "na27@hood.edu";
export const REPOSITORY_URL = "https://github.com/naylinnaungHoodedu/qcai-studio";
export const ATTRIBUTION_STATEMENT =
  "QC+AI Studio is a human-directed, AI-assisted learning platform built and significantly enhanced using OpenAI Codex.";

export const MODULE_SLUGS = [
  "nisq-hybrid-workflows",
  "ai-for-quantum-hardware",
  "quantum-enhanced-applications",
  "representation-explainability",
  "industry-use-cases",
  "thermodynamics-roadmap",
  "hardware-constrained-introduction",
  "hardware-constrained-models",
  "intermediate-quantum-programming",
  "advanced-quantum-software",
  "quantum-finance-programming",
];

export const LESSON_SLUGS = [
  "nisq-reality-overview",
  "ai4qc-routing-and-optimization",
  "hybrid-applications-healthcare-vision",
  "clinical-and-kernel-qcai-systems",
  "representation-language-and-xai",
  "industry-use-cases",
  "thermodynamics-and-roadmap",
  "introduction-to-hardware-constrained-learning",
  "hardware-constrained-qcai-models",
  "intermediate-quantum-programming-patterns",
  "advanced-quantum-software-development",
  "quantum-finance-programming-and-optimization",
];

export const STATIC_ROUTE_LASTMOD: Record<string, string> = {
  "/": "2026-03-30T00:00:00Z",
  "/modules": "2026-03-30T00:00:00Z",
  "/simulations": "2026-03-30T00:00:00Z",
  "/about": "2026-03-28T00:00:00Z",
  "/whats-new": "2026-03-30T00:00:00Z",
  "/syllabus": "2026-03-28T00:00:00Z",
  "/privacy": "2026-03-29T00:00:00Z",
  "/terms": "2026-03-29T00:00:00Z",
  "/support": "2026-03-30T00:00:00Z",
  "/status": "2026-03-31T00:00:00Z",
  "/accessibility": "2026-03-31T00:00:00Z",
  "/attribution": "2026-03-29T00:00:00Z",
};

export const MODULE_ROUTE_LASTMOD: Record<string, string> = {
  "nisq-hybrid-workflows": "2026-03-28T00:00:00Z",
  "ai-for-quantum-hardware": "2026-03-28T00:00:00Z",
  "quantum-enhanced-applications": "2026-03-28T00:00:00Z",
  "representation-explainability": "2026-03-28T00:00:00Z",
  "industry-use-cases": "2026-03-29T00:00:00Z",
  "thermodynamics-roadmap": "2026-03-28T00:00:00Z",
  "hardware-constrained-introduction": "2026-03-30T00:00:00Z",
  "hardware-constrained-models": "2026-03-30T00:00:00Z",
  "intermediate-quantum-programming": "2026-03-30T00:00:00Z",
  "advanced-quantum-software": "2026-03-30T00:00:00Z",
  "quantum-finance-programming": "2026-03-30T00:00:00Z",
};

export const LESSON_ROUTE_LASTMOD: Record<string, string> = {
  "nisq-reality-overview": "2026-03-29T00:00:00Z",
  "ai4qc-routing-and-optimization": "2026-03-29T00:00:00Z",
  "hybrid-applications-healthcare-vision": "2026-03-28T00:00:00Z",
  "clinical-and-kernel-qcai-systems": "2026-03-28T00:00:00Z",
  "representation-language-and-xai": "2026-03-28T00:00:00Z",
  "industry-use-cases": "2026-03-29T00:00:00Z",
  "thermodynamics-and-roadmap": "2026-03-28T00:00:00Z",
  "introduction-to-hardware-constrained-learning": "2026-03-30T00:00:00Z",
  "hardware-constrained-qcai-models": "2026-03-30T00:00:00Z",
  "intermediate-quantum-programming-patterns": "2026-03-30T00:00:00Z",
  "advanced-quantum-software-development": "2026-03-30T00:00:00Z",
  "quantum-finance-programming-and-optimization": "2026-03-30T00:00:00Z",
};
