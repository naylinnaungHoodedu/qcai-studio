import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { fetchCourseOverview } from "@/lib/api";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import {
  ABOUT_AUDIENCE_GROUPS,
  ABOUT_LEARNING_PROGRESSION,
  COURSE_SCOPE_NOTE,
  ENGINEERING_READING_NOTES,
  INDUSTRY_METHOD_NOTE,
} from "@/lib/public-course";
import { CONTACT_EMAIL, OWNER_NAME, REPOSITORY_URL, SITE_URL } from "@/lib/site";

const FALLBACK_SOURCE_ASSETS = [
  {
    id: "doc-qcai-2026",
    title: "Quantum Computing AI Research Synthesis 2026",
    kind: "document",
    filename: "Quantum Computing AI Research Synthesis 2026.docx",
    description: "Curated workshop-proceedings synthesis used to shape the advanced QC+AI lessons.",
  },
  {
    id: "doc-qcai-2025",
    title: "Analyzing Quantum Computing and AI Paper 2025",
    kind: "document",
    filename: "Analyzing Quantum Computing and AI Paper 2025.docx",
    description: "Proceedings analysis that anchors the earlier research baseline and topic progression.",
  },
  {
    id: "doc-industry-use-cases",
    title: "Quantum Computing and Artificial Intelligence Industry Use Cases",
    kind: "document",
    filename: "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
    description: "Industry framing that connects the curriculum to commercial and applied system design.",
  },
  {
    id: "doc-module2-routing",
    title: "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
    kind: "document",
    filename: "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
    description: "Local authored source focused on logistics QUBO reformulation, graph shrinking, augmented Lagrangian control, and routing-aware execution.",
  },
  {
    id: "doc-module3-vision",
    title: "Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
    kind: "document",
    filename: "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx",
    description: "Local authored source focused on QViTs, QGNNs, conditioned quantum diffusion, biomedical imaging, and orchestration limits in hybrid perception systems.",
  },
  {
    id: "doc-module4-expressivity",
    title: "Expressive Bottlenecks: Compression, Language, and Explanation",
    kind: "document",
    filename: "Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx",
    description: "Local authored source focused on expressive bottlenecks in graph reasoning, diffusion, language adaptation, quantum compression, and explainability.",
  },
  {
    id: "doc-module6-systems",
    title: "From Algorithmic Novelty to Sustainable Hybrid Systems",
    kind: "document",
    filename: "Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.docx",
    description: "Local authored capstone source focused on hybrid algorithms, AI4QC orchestration, Industry 5.0 infrastructure, thermodynamic agents, and post-quantum transition planning.",
  },
  {
    id: "doc-hcl-introduction",
    title: "Introduction to Hardware-Constrained QC+AI",
    kind: "document",
    filename: "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    description: "Local authored source that extends the curriculum with hardware-constrained learning foundations.",
  },
  {
    id: "doc-hcl-models",
    title: "Hardware-Constrained QC+AI Models",
    kind: "document",
    filename: "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx",
    description: "Local authored source focused on model families, trainability barriers, and validation strategy.",
  },
  {
    id: "doc-hcl-programming",
    title: "Intermediate Quantum Programming for Hardware-Constrained QC+AI",
    kind: "document",
    filename: "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    description: "Local authored source focused on device-first programming patterns, debugging, and measurement strategy.",
  },
  {
    id: "doc-hcl-software",
    title: "Advanced Quantum Software Development for Hardware-Constrained QC+AI",
    kind: "document",
    filename: "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    description: "Local authored source covering compilation, MLIR, caching, pulse control, and reliability engineering.",
  },
  {
    id: "doc-hcl-finance",
    title: "Quantum Finance Programming and Optimization for Hardware-Constrained QC+AI",
    kind: "document",
    filename: "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    description: "Local authored source focused on finance workloads, hybrid optimization, and model-risk-aware QC+AI deployment.",
  },
  {
    id: "video-qcai-2025",
    title: "Quantum Computing and Artificial Intelligence 2025",
    kind: "video",
    filename: "Quantum Computing and Artificial Intelligence 2025.mp4",
    description: "Lecture media used to reinforce the NISQ, routing, and hybrid-workflow portions of the course.",
  },
  {
    id: "video-qcai-2026",
    title: "Quantum Computing and Artificial Intelligence 2026",
    kind: "video",
    filename: "Quantum Computing and Artificial Intelligence 2026.mp4",
    description: "Lecture media tied to the applications, representational bottlenecks, and systems roadmap modules.",
  },
  {
    id: "video-industry-use-cases",
    title: "Industry Use Cases",
    kind: "video",
    filename: "Industry Use Cases.mp4",
    description: "Lecture media connecting the curriculum to industry readiness, migration planning, and sector-specific deployment tradeoffs.",
  },
  {
    id: "video-module2-routing",
    title: "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
    kind: "video",
    filename: "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
    description: "Lecture media focused on graph shrinking, RL-tuned penalty control, nested qubit routing, and quantum logistics systems design.",
  },
  {
    id: "video-module3-vision",
    title: "Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
    kind: "video",
    filename: "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4",
    description: "Lecture media focused on QViTs, graph architectures, few-shot diffusion, and the orchestration limits that still bound deployable hybrid perception systems.",
  },
  {
    id: "video-module4-expressivity",
    title: "Expressive Bottlenecks: Compression, Language, and Explanation",
    kind: "video",
    filename: "Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4",
    description: "Lecture media focused on expressive bottlenecks, quantum representational geometry, hybrid compression, semantic embeddings, and explainability under systems constraints.",
  },
  {
    id: "video-module6-systems",
    title: "From Algorithmic Novelty to Sustainable Hybrid Systems",
    kind: "video",
    filename: "Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.mp4",
    description: "Lecture media focused on hybrid algorithmic foundations, sustainable infrastructure, language efficiency, quantum agents, and long-horizon security transition planning.",
  },
  {
    id: "video-hcl-introduction",
    title: "Introduction to Hardware-Constrained QC+AI",
    kind: "video",
    filename: "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    description: "Lecture media introducing the hardware-first worldview, trainability limits, and near-term QC+AI design discipline.",
  },
  {
    id: "video-hcl-models",
    title: "Hardware-Constrained QC+AI Models",
    kind: "video",
    filename: "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
    description: "Lecture media comparing model families, kernel concentration, and validation criteria under NISQ constraints.",
  },
  {
    id: "video-hcl-programming",
    title: "Intermediate Quantum Programming for Hardware-Constrained QC+AI",
    kind: "video",
    filename: "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    description: "Lecture media focused on parameter-shift gradients, shot allocation, measurement grouping, and diagnostics.",
  },
  {
    id: "video-hcl-software",
    title: "Advanced Quantum Software Development for Hardware-Constrained QC+AI",
    kind: "video",
    filename: "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    description: "Lecture media focused on compiler design, MLIR, caching, pulse-level optimization, and reliability engineering.",
  },
  {
    id: "video-hcl-finance",
    title: "Quantum Finance Programming and Optimization for Hardware-Constrained QC+AI",
    kind: "video",
    filename: "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    description: "Lecture media focused on portfolio optimization, pricing, anomaly workflows, and finance-specific model-risk gates.",
  },
] as const;

const ENGINEERING_SURFACES = [
  {
    eyebrow: "Backend",
    title: "FastAPI service architecture",
    description:
      "The platform exposes a substantial API surface for lessons, grounded QA, analytics, projects, and interactive practice modes.",
    bullets: [
      "11 route groups cover content, auth, search, QA, analytics, assets, arena, builder, insights, projects, and admin flows.",
      "SQLAlchemy and Alembic support persistence across learner activity, notes, reviews, and progress data.",
      "Authenticated asset delivery includes byte-range streaming so MP4 playback and seeking work reliably.",
    ],
  },
  {
    eyebrow: "AI and retrieval",
    title: "Grounded intelligence instead of generic chat",
    description:
      "QC+AI Studio uses retrieval-first AI services so niche quantum topics stay tied to evidence instead of model improvisation.",
    bullets: [
      "LangChain and OpenAI GPT-4.1-mini drive citation-first Q&A against the curated corpus when the OpenAI key is provisioned.",
      "Pinecone-backed hybrid retrieval activates only when OpenAI and Pinecone secrets are present; otherwise the site stays on grounded lexical fallback.",
      "Adaptive insights, skill-gap reporting, and next-step recommendations extend the platform beyond static content delivery.",
    ],
  },
  {
    eyebrow: "Frontend and cloud",
    title: "Modern app delivery with production posture",
    description:
      "The learner experience is built as a real web application with secure public and protected surfaces, not as a static microsite.",
    bullets: [
      "Next.js 16.2.1, React 19.2.4, TypeScript, and App Router power the frontend experience.",
      "Proxy-based guest auth and CSRF protection keep public study surfaces usable without weakening mutation safety.",
      "Docker, Cloud Run, Cloud SQL, GCS, Secret Manager, and Cloud DNS form the intended production deployment stack.",
    ],
  },
] as const;

const BUILD_PRACTICES = [
  "Human review stays responsible for scope, architecture, acceptance criteria, and final publication.",
  "AI assistance accelerated implementation, refinement, testing, infrastructure, and documentation work across the stack.",
  "Claims on the public site are strongest when they can be tied back to the live codebase, a source asset, or a reproducible test run.",
] as const;

function renderAudienceIcon(icon: string): ReactNode {
  switch (icon) {
    case "developers":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <rect height="12" rx="2.5" width="16" x="4" y="5" />
          <path d="M8 19h8" />
        </svg>
      );
    case "scientists":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="M10 4h4" />
          <path d="M11 4v5l-5 8a3 3 0 0 0 2.6 4.5h6.8A3 3 0 0 0 18 17l-5-8V4" />
        </svg>
      );
    case "researchers":
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <circle cx="9" cy="10" r="3.5" />
          <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
          <path d="M18.5 8.5a2.5 2.5 0 1 1-.001 5.001A2.5 2.5 0 0 1 18.5 8.5Z" />
          <path d="M16.5 19a4 4 0 0 1 4-4" />
        </svg>
      );
    case "students":
    default:
      return (
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
          <path d="m4 9 8-4 8 4-8 4-8-4Z" />
          <path d="M7 11.5V15c0 1.2 2.2 3 5 3s5-1.8 5-3v-3.5" />
        </svg>
      );
  }
}

export const metadata: Metadata = buildPageMetadata({
  title: "About the QC+AI Learning Platform",
  description:
    "Learn what QC+AI Studio is, why it was built, how the curriculum is curated, and how the live platform is engineered and reviewed.",
  path: "/about",
});

export default async function AboutPage() {
  const course = await fetchCourseOverview().catch(() => null);
  const sourceAssets = course?.source_assets.length ? course.source_assets : FALLBACK_SOURCE_ASSETS;
  const moduleCount = course?.modules.length ?? 11;
  const lessonCount = course?.modules.reduce((count, module) => count + module.lesson_slugs.length, 0) ?? 12;
  const videoCount = sourceAssets.filter((asset) => asset.kind.toLowerCase() === "video").length || 8;
  const documentCount = Math.max(sourceAssets.length - videoCount, 0);
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: "QC+AI Studio",
      url: `${SITE_URL}/about`,
      founder: OWNER_NAME,
      email: CONTACT_EMAIL,
      description:
        "QC+AI Studio is a source-grounded learning platform for quantum computing and AI built around hybrid-system design, hardware realism, and transparent public evaluation.",
    },
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "About", path: "/about" },
    ]),
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="about-organization-jsonld" />
      <section className="hero about-hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "About" },
            ]}
          />
          <p className="eyebrow">About QC+AI Studio</p>
          <h1>A public QC+AI learning platform built for technical trust, not just surface polish.</h1>
          <p className="hero-text">
            QC+AI Studio is a graduate-level learning environment for quantum computing and artificial intelligence. It turns curated proceedings, applied industry material, and lecture assets into a structured web product with modules, lessons, grounded Q&amp;A, projects, and learner analytics.
          </p>
          <p className="hero-text">{COURSE_SCOPE_NOTE}</p>
          <div className="button-row">
            <Link className="primary-button" href="/modules">
              Review the curriculum
            </Link>
            <Link className="secondary-button" href="/attribution">
              Read attribution
            </Link>
            <a className="secondary-button" href={REPOSITORY_URL} rel="noreferrer" target="_blank">
              Inspect GitHub
            </a>
          </div>
        </div>

        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Creator</span>
            <strong className="about-metric-value">{OWNER_NAME}</strong>
            <p>Product ownership, domain direction, and final review remain human-led.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Modules</span>
            <strong className="about-metric-value">{moduleCount}</strong>
            <p>Structured curriculum blocks in the current public studio track.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Lessons</span>
            <strong className="about-metric-value">{lessonCount}</strong>
            <p>Focused learning units connected to search, flashcards, quizzes, and projects.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Corpus</span>
            <strong className="about-metric-value">{documentCount + videoCount}</strong>
            <p>
              {documentCount} documents and {videoCount} videos shape the public curriculum.
            </p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Audience and progression</p>
          <h2>Who is it for?</h2>
          <p>
            The platform is meant for technically serious learners who want a compact route into QC+AI without losing sight of engineering constraints. The progression below makes the intended learning arc explicit instead of leaving the course sequence implicit.
          </p>
        </div>
        <div className="audience-grid">
          {ABOUT_AUDIENCE_GROUPS.map((group) => (
            <article className="audience-card" key={group.title}>
              <div className="audience-card-icon">{renderAudienceIcon(group.icon)}</div>
              <div className="stack">
                <h3>{group.title}</h3>
                <p>{group.description}</p>
              </div>
            </article>
          ))}
        </div>
        <article className="panel progression-shell">
          <div className="section-heading">
            <p className="eyebrow">Learning progression</p>
            <h2>Learning progression</h2>
            <p>
              The public course now makes the module path easier to read as a progression rather than a flat list. Each stage below points to the relevant module range inside the current eleven-module track.
            </p>
          </div>
          <div className="progression-track">
            <div aria-hidden="true" className="progression-line" />
            {ABOUT_LEARNING_PROGRESSION.map((step, index) => (
              <article
                className={`progression-step ${index % 2 === 1 ? "is-offset" : ""}`}
                key={step.title}
              >
                <span className="progression-step-dot" aria-hidden="true" />
                <div className="progression-step-card">
                  <div className="button-row">
                    <span className="status-pill in_progress">{step.moduleRange}</span>
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.summary}</p>
                </div>
              </article>
            ))}
          </div>
        </article>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Mission</p>
          <h2>Why this product exists</h2>
          <p>
            Most QC+AI resources split in the wrong direction: either they stay too abstract to help engineers reason about real systems, or they oversimplify quantum claims into marketing language. This platform is meant to create a middle path anchored in evidence, architecture, and practical skepticism.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Public promise</p>
            <h2>What the site should make clear</h2>
            <ul className="goal-list">
              <li>The curriculum is source-grounded and inspectable.</li>
              <li>The course prioritizes hybrid-system design under hardware limits.</li>
              <li>The product is honest about what is fully operational, what is guest-mode, and what is still environment-gated.</li>
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">Creator context</p>
            <h2>Ownership and contact</h2>
            <p>
              {OWNER_NAME} remains responsible for product direction, publication decisions, and final review. Questions about attribution, evaluation, or the public course experience can be sent to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
            </p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Editorial method</p>
          <h2>How the content is framed</h2>
          <p>
            The site does not treat every source equally. Proceedings-style research, applied industry synthesis, and lecture media play different roles inside the learning path, and the product now says so explicitly.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Reading lens</p>
            <h2>How to interpret the lessons</h2>
            <ul className="goal-list">
              {ENGINEERING_READING_NOTES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article className="panel">
            <p className="eyebrow">Industry synthesis note</p>
            <h2>Why Module 5 is labeled carefully</h2>
            <p>{INDUSTRY_METHOD_NOTE}</p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Verification and review</p>
          <h2>How the product is kept honest</h2>
          <p>
            A public learning product should not ask visitors to trust vague claims. The implementation is backed by tests, deployable infrastructure, source-linked retrieval, and explicit disclosure of environment-gated capabilities.
          </p>
        </div>
        <div className="module-grid">
          {BUILD_PRACTICES.map((item) => (
            <article className="panel" key={item}>
              <div className="stack">
                <p className="eyebrow">Practice</p>
                <h2>{item}</h2>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Architecture snapshot</p>
          <h2>Full-stack engineering footprint</h2>
          <p>
            The public site is the frontend of a larger product surface that includes content assembly, retrieval, analytics, project workflows, and secure media delivery.
          </p>
        </div>
        <div className="module-grid">
          {ENGINEERING_SURFACES.map((surface) => (
            <article className="panel" key={surface.title}>
              <div className="stack">
                <p className="eyebrow">{surface.eyebrow}</p>
                <h2>{surface.title}</h2>
                <p>{surface.description}</p>
                <ul className="goal-list">
                  {surface.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Explore next</p>
          <h2>Read the curriculum, then inspect the implementation details</h2>
          <p>
            The curriculum hub now covers prerequisites, project rubrics, public guest access, and methodological notes. The attribution page covers the human-directed AI-assisted build process in more detail.
          </p>
        </div>
        <div className="button-row">
          <Link className="primary-button" href="/modules">
            Open modules
          </Link>
          <Link className="secondary-button" href="/syllabus">
            Open syllabus
          </Link>
          <Link className="secondary-button" href="/attribution">
            Open attribution
          </Link>
        </div>
      </section>
    </div>
  );
}
