import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { ModuleProgress, ModuleSummary } from "@/lib/types";

type ModuleCardMeta = {
  accent: string;
  accentSoft: string;
  icon: string;
  level: "Beginner" | "Intermediate" | "Advanced";
  tags: string[];
  footer: string;
};

const MODULE_CARD_META: Record<string, ModuleCardMeta> = {
  "nisq-hybrid-workflows": {
    accent: "#18c8ff",
    accentSoft: "rgba(24, 200, 255, 0.2)",
    icon: "orbit",
    level: "Beginner",
    tags: ["QAI vs AI4QC", "NISQ", "Hybrid loops", "Bottlenecks"],
    footer: "Grounded in the QC+AI 2025 and 2026 proceedings introduction material.",
  },
  "ai-for-quantum-hardware": {
    accent: "#8f5dff",
    accentSoft: "rgba(143, 93, 255, 0.2)",
    icon: "routing",
    level: "Intermediate",
    tags: ["Routing", "Graph shrinking", "QUBO", "RL-Q-ALM"],
    footer: "Grounded in routing, logistics, and graph-reduction source sections.",
  },
  "quantum-enhanced-applications": {
    accent: "#27d8c0",
    accentSoft: "rgba(39, 216, 192, 0.2)",
    icon: "layers",
    level: "Intermediate",
    tags: ["Vision", "Healthcare", "Few-shot", "Kernels"],
    footer: "Grounded in hybrid application papers across vision, healthcare, and few-shot learning.",
  },
  "representation-explainability": {
    accent: "#a24dff",
    accentSoft: "rgba(162, 77, 255, 0.2)",
    icon: "grid",
    level: "Advanced",
    tags: ["Compression", "Language", "QGSHAP", "Representations"],
    footer: "Grounded in quINR, QuCoWE, and exact explainability source material.",
  },
  "industry-use-cases": {
    accent: "#ff9f2f",
    accentSoft: "rgba(255, 159, 47, 0.2)",
    icon: "briefcase",
    level: "Intermediate",
    tags: ["Finance", "Healthcare", "Cybersecurity", "Commercialization"],
    footer: "Grounded in the curated industry-use-cases document rather than proceedings-only evidence.",
  },
  "thermodynamics-roadmap": {
    accent: "#ff6997",
    accentSoft: "rgba(255, 105, 151, 0.2)",
    icon: "energy",
    level: "Advanced",
    tags: ["Resource efficiency", "Roadmap", "Thermodynamics", "Systems"],
    footer: "Grounded in the 2026 systems and thermodynamic synthesis sections.",
  },
  "hardware-constrained-introduction": {
    accent: "#27d86f",
    accentSoft: "rgba(39, 216, 111, 0.2)",
    icon: "spark",
    level: "Beginner",
    tags: ["Noise", "Shots", "Barren plateaus", "Goldilocks design"],
    footer: "Grounded in the local introduction document for hardware-constrained QC+AI.",
  },
  "hardware-constrained-models": {
    accent: "#4da3ff",
    accentSoft: "rgba(77, 163, 255, 0.2)",
    icon: "models",
    level: "Intermediate",
    tags: ["VQCs", "Kernel methods", "CV-QNN", "Validation"],
    footer: "Grounded in the local models document and its acceptance-criteria sections.",
  },
  "intermediate-quantum-programming": {
    accent: "#1bd4ff",
    accentSoft: "rgba(27, 212, 255, 0.2)",
    icon: "terminal",
    level: "Intermediate",
    tags: ["Parameter shift", "Shot allocation", "Grouping", "Debugging"],
    footer: "Grounded in the intermediate programming document and its hardware test strategy.",
  },
  "advanced-quantum-software": {
    accent: "#b16dff",
    accentSoft: "rgba(177, 109, 255, 0.2)",
    icon: "compile",
    level: "Advanced",
    tags: ["MLIR", "Pulse control", "Caching", "Reliability"],
    footer: "Grounded in the advanced software-development document and workflow mappings.",
  },
  "quantum-finance-programming": {
    accent: "#ffb020",
    accentSoft: "rgba(255, 176, 32, 0.2)",
    icon: "finance",
    level: "Advanced",
    tags: ["Portfolio optimization", "Option pricing", "Model risk", "QUBO"],
    footer: "Grounded in the local quantum-finance programming and optimization document.",
  },
};

const DEFAULT_CARD_META: ModuleCardMeta = {
  accent: "#1bd4ff",
  accentSoft: "rgba(27, 212, 255, 0.2)",
  icon: "orbit",
  level: "Intermediate",
  tags: ["Hardware aware", "Hybrid", "QC+AI"],
  footer: "Grounded in curated local QC+AI source material.",
};

function formatStatus(status: string): string {
  if (status === "in_progress") {
    return "In progress";
  }
  if (status === "completed") {
    return "Completed";
  }
  return "Not started";
}

function renderModuleIcon(icon: string): ReactNode {
  switch (icon) {
    case "routing":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <circle cx="6" cy="18" r="2.2" />
          <circle cx="18" cy="6" r="2.2" />
          <circle cx="18" cy="18" r="2.2" />
          <path d="M8 17.2h6.8V8.8M8.2 16.2l7.8-7.8" />
        </svg>
      );
    case "layers":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="m12 4 7 3.5-7 3.5-7-3.5L12 4Z" />
          <path d="m5 12 7 3.5 7-3.5" />
          <path d="m5 16.5 7 3.5 7-3.5" />
        </svg>
      );
    case "grid":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <rect height="5" rx="1" width="5" x="4" y="4" />
          <rect height="5" rx="1" width="5" x="15" y="15" />
          <rect height="5" rx="1" width="5" x="4" y="15" />
          <path d="M9 6.5h6v11" />
        </svg>
      );
    case "briefcase":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M4 8h16v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8Z" />
          <path d="M9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
          <path d="M4 12h16" />
        </svg>
      );
    case "energy":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M12 3v7" />
          <path d="M8.2 6.2 12 10l3.8-3.8" />
          <path d="M7 14a5 5 0 1 0 10 0" />
          <path d="M12 14v7" />
        </svg>
      );
    case "spark":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />
          <path d="M18 16.5 19 19l2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1 1-2.5Z" />
        </svg>
      );
    case "models":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <rect height="4" rx="1" width="6" x="4" y="5" />
          <rect height="4" rx="1" width="6" x="14" y="5" />
          <rect height="4" rx="1" width="6" x="9" y="15" />
          <path d="M7 9v2.5h10V9M12 11.5V15" />
        </svg>
      );
    case "terminal":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <rect height="16" rx="3" width="18" x="3" y="4" />
          <path d="m7 9 3 3-3 3M12 15h5" />
        </svg>
      );
    case "compile":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M4 12h7" />
          <path d="m8 8 4 4-4 4" />
          <path d="M14 7h6M14 12h6M14 17h6" />
        </svg>
      );
    case "finance":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M5 18V9" />
          <path d="M10 18V12" />
          <path d="M15 18V7" />
          <path d="M20 18V4" />
          <path d="m4 15 5-4 4 2 7-7" />
        </svg>
      );
    case "orbit":
    default:
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="5.5" />
          <circle cx="12" cy="12" fill="currentColor" r="1.5" />
        </svg>
      );
  }
}

export function ModuleCard({
  module,
  moduleNumber,
  progress,
}: {
  module: ModuleSummary;
  moduleNumber: number;
  progress?: ModuleProgress;
}) {
  const meta = MODULE_CARD_META[module.slug] ?? DEFAULT_CARD_META;
  const firstLessonHref = module.lesson_slugs[0] ? `/lessons/${module.lesson_slugs[0]}` : "/syllabus";
  const secondaryLabel = module.lesson_slugs[0] ? "Open first lesson" : "Review syllabus";

  return (
    <article
      className="module-card"
      style={
        {
          ["--module-accent" as string]: meta.accent,
          ["--module-accent-soft" as string]: meta.accentSoft,
        } as CSSProperties
      }
    >
      <div className="module-card-top">
        <div className="module-card-top-left">
          <div className="module-card-symbol">{renderModuleIcon(meta.icon)}</div>
          <div className="module-card-badges">
            <span className={`module-level-pill module-level-pill--${meta.level.toLowerCase()}`}>
              {meta.level}
            </span>
            {progress ? (
              <span className={`status-pill ${progress.status}`}>{formatStatus(progress.status)}</span>
            ) : null}
          </div>
        </div>
        <span aria-label={`Module ${moduleNumber}`} className="module-card-number">
          {moduleNumber}
        </span>
      </div>

      <div className="stack module-card-copy">
        <h3>{module.title}</h3>
        <p>{module.summary}</p>
      </div>

      <div className="module-card-tags">
        {meta.tags.map((tag) => (
          <span className="module-chip" key={tag}>
            {tag}
          </span>
        ))}
      </div>

      {progress ? (
        <div className="module-card-progress">
          <div className="module-progress-track" aria-hidden="true">
            <span style={{ width: `${progress.progress_percent}%` }} />
          </div>
          <p className="muted">
            {progress.completed_lessons} / {progress.total_lessons} lessons completed
            {progress.average_score_percent != null ? ` | avg quiz ${progress.average_score_percent}%` : ""}
          </p>
        </div>
      ) : null}

      <div aria-hidden="true" className="module-card-divider" />

      <div className="module-card-actions">
        <Link className="primary-button module-card-button" href={`/modules/${module.slug}`}>
          Visit course
        </Link>
        <Link className="secondary-button module-card-button" href={firstLessonHref}>
          {secondaryLabel}
        </Link>
      </div>

      <p className="module-card-footnote">{meta.footer}</p>
    </article>
  );
}
