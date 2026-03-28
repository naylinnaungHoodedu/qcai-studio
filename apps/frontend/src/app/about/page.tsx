import type { Metadata } from "next";
import Link from "next/link";

import { fetchCourseOverview } from "@/lib/api";
import { COURSE_REFERENCES } from "@/lib/course-references";
import { buildPageMetadata } from "@/lib/metadata";
import { CONTACT_EMAIL, OWNER_NAME, REPOSITORY_URL } from "@/lib/site";

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
    id: "video-lecture-1",
    title: "QC+AI lecture asset 1",
    kind: "video",
    filename: "qcai-lecture-1.mp4",
    description: "Lecture media used to reinforce the hardware and hybrid-workflow portions of the course.",
  },
  {
    id: "video-lecture-2",
    title: "QC+AI lecture asset 2",
    kind: "video",
    filename: "qcai-lecture-2.mp4",
    description: "Lecture media tied to the application and explainability modules.",
  },
  {
    id: "video-lecture-3",
    title: "QC+AI lecture asset 3",
    kind: "video",
    filename: "qcai-lecture-3.mp4",
    description: "Lecture media supporting the roadmap, thermodynamics, and future-facing sections.",
  },
] as const;

const ENGINEERING_SURFACES = [
  {
    eyebrow: "Backend",
    title: "FastAPI service architecture",
    description:
      "The platform exposes a substantial API surface for lessons, grounded QA, analytics, projects, and game-like practice modes.",
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
      "LangChain and OpenAI GPT-4.1-mini drive citation-first Q&A against the curated corpus.",
      "Pinecone is available for production retrieval, with local grounded fallbacks for resilient development and demos.",
      "Adaptive insights, skill-gap reporting, and next-step recommendations extend the platform beyond static content delivery.",
    ],
  },
  {
    eyebrow: "Frontend and cloud",
    title: "Modern app delivery with production posture",
    description:
      "The learner experience is built as a real web application with secure public and protected surfaces, not as a static microsite.",
    bullets: [
      "Next.js 16, React 19, TypeScript, and App Router power the frontend experience.",
      "Proxy-based guest auth and CSRF protection keep protected study surfaces usable without weakening mutation safety.",
      "Docker, Cloud Run, Cloud SQL, GCS, Secret Manager, and Cloud DNS form the intended production deployment stack.",
    ],
  },
] as const;

const CODEX_WORKSTREAMS = [
  {
    eyebrow: "Backend",
    title: "Route and service implementation",
    description:
      "Codex was used to implement and refine the backend route modules, course assembly pipeline, analytics services, and interactive learning engines.",
  },
  {
    eyebrow: "Frontend",
    title: "Pages, flows, and interaction design",
    description:
      "Codex assisted with the Next.js pages, TypeScript data wiring, video delivery UX, grounded study flows, and public platform surfaces.",
  },
  {
    eyebrow: "Verification",
    title: "Testing and hardening",
    description:
      "The project uses backend tests, frontend integration tests, linting, and production builds to verify feature behavior rather than relying on screenshots.",
  },
  {
    eyebrow: "Delivery",
    title: "Infrastructure and submission packaging",
    description:
      "Codex also accelerated Cloud Run, container, and documentation work so the product story, deployment shape, and attribution stayed coherent end to end.",
  },
] as const;

const DIFFERENTIATORS = [
  "Graduate-level QC+AI focus instead of a generic chatbot or a shallow educational shell.",
  "Citation-grounded answers anchored to real proceedings, use-case analysis, and lecture assets.",
  "A real full-stack product footprint spanning backend services, frontend UX, storage, auth, and deployment infrastructure.",
  "Multiple active-learning loops, including flashcards, quizzes, notes, projects, analytics, arena play, and builder scenarios.",
] as const;

const LESSONS_LEARNED = [
  "Grounding is essential for educational AI on niche technical subjects because confident hallucinations are otherwise too easy.",
  "AI-assisted development works best when the human owner sets scope, quality bar, and acceptance criteria across the whole stack.",
  "Security details like CSP, guest mutation protection, and proper streaming semantics matter even in student-led products.",
  "Documentation and attribution are part of product quality, not cleanup chores to postpone until the end.",
] as const;

export const metadata: Metadata = buildPageMetadata({
  title: "About",
  description:
    "Learn what QC+AI Studio is, why it was built, how the curriculum is grounded, and how the platform was engineered with OpenAI Codex assistance.",
  path: "/about",
});

export default async function AboutPage() {
  const course = await fetchCourseOverview().catch(() => null);
  const sourceAssets = course?.source_assets.length ? course.source_assets : FALLBACK_SOURCE_ASSETS;
  const moduleCount = course?.modules.length ?? 6;
  const totalLessons =
    course?.modules.reduce((count, module) => count + module.lesson_slugs.length, 0) ?? 7;
  const sourceAssetCount = sourceAssets.length;
  const videoCount =
    sourceAssets.filter((asset) => asset.kind.toLowerCase() === "video").length || 3;
  const documentCount = Math.max(sourceAssetCount - videoCount, 0);
  const startHref = course?.modules[0] ? `/modules/${course.modules[0].slug}` : "/syllabus";
  const courseSummary =
    course?.summary ??
    "QC+AI Studio turns curated QC+AI proceedings, industry-use-case analysis, and lecture media into a structured interactive course.";

  const platformPillars = [
    {
      eyebrow: "Curriculum",
      title: "Follow a structured six-module path",
      description:
        "The course moves from NISQ-era realities and hardware optimization into applications, explainability, industry use cases, and roadmap thinking.",
      href: "/syllabus",
      action: "View syllabus",
    },
    {
      eyebrow: "Grounded retrieval",
      title: "Ask questions against cited source material",
      description:
        "Search and lesson-level Q&A stay tied to source passages, sections, and timestamps instead of drifting into unsupported answers.",
      href: "/search",
      action: "Search the materials",
    },
    {
      eyebrow: "Retention",
      title: "Study through flashcards, quizzes, and notes",
      description:
        "Lessons are designed for active recall and durable learning, not passive reading, with practice surfaces built directly into the course flow.",
      href: startHref,
      action: "Start a lesson",
    },
    {
      eyebrow: "Analytics",
      title: "Track progress, momentum, and skill gaps",
      description:
        "The dashboard combines completion, performance, focus, readiness, and AI-generated next steps into a single learner view.",
      href: "/dashboard",
      action: "Open dashboard",
    },
    {
      eyebrow: "Projects",
      title: "Build portfolio-grade QC+AI work",
      description:
        "Project workflows combine technical briefs, AI feedback, submission tracking, and peer review so learners can produce evidence of skill.",
      href: "/projects",
      action: "Open projects",
    },
    {
      eyebrow: "Practice modes",
      title: "Compete in the arena or build dependency maps",
      description:
        "Arena and Builder extend the platform into live recall, systems thinking, and microlearning construction instead of stopping at content delivery.",
      href: "/arena",
      action: "Enter arena",
      secondaryHref: "/builder",
      secondaryAction: "Open builder",
    },
  ] as const;

  return (
    <div className="page-stack">
      <section className="hero about-hero">
        <div className="hero-copy">
          <p className="eyebrow">About QC+AI Studio</p>
          <h1>A source-grounded QC+AI learning platform built around real research, real media, and real engineering constraints.</h1>
          <p className="hero-text">
            QC+AI Studio is a graduate-level learning environment for quantum computing and artificial intelligence. It converts curated workshop
            proceedings, industry-use-case analysis, and lecture videos into a structured web platform with lessons, retrieval, practice loops,
            and learner analytics.
          </p>
          <p className="hero-text">
            The goal is to teach what actually matters in practice: routing overhead, qubit scarcity, hybrid orchestration, noise, explainability,
            and commercialization context, not just abstract definitions.
          </p>
          <div className="button-row">
            <Link className="primary-button" href={startHref}>
              Start the course
            </Link>
            <Link className="secondary-button" href="/syllabus">
              Review syllabus
            </Link>
            <a className="secondary-button" href={REPOSITORY_URL} rel="noreferrer" target="_blank">
              Inspect GitHub
            </a>
          </div>
        </div>

        <div className="hero-grid">
          <div className="hero-panel stack">
            <div className="stack">
              <p className="eyebrow">Creator and context</p>
              <h2>{OWNER_NAME}</h2>
              <p className="muted">
                Hood College, Frederick, Maryland. Product ownership, domain direction, and final review remain human-led, with OpenAI Codex used as
                the primary coding assistant across the stack.
              </p>
              <p className="muted">
                This public page documents the purpose, corpus, and engineering footprint behind the live platform at qantumlearn.academy.
              </p>
              <p className="muted">
                Contact: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
              </p>
            </div>
            <div className="button-row">
              <Link className="secondary-button" href="/attribution">
                Read attribution
              </Link>
              <Link className="secondary-button" href="/privacy">
                Privacy details
              </Link>
            </div>
          </div>

          <div className="analytics-metric-grid">
            <article className="metric-card">
              <div className="stack">
                <span className="eyebrow">Modules</span>
                <strong className="about-metric-value">{moduleCount}</strong>
                <span className="muted">Structured curriculum blocks</span>
              </div>
            </article>
            <article className="metric-card">
              <div className="stack">
                <span className="eyebrow">Lessons</span>
                <strong className="about-metric-value">{totalLessons}</strong>
                <span className="muted">Interactive learning units</span>
              </div>
            </article>
            <article className="metric-card">
              <div className="stack">
                <span className="eyebrow">Source assets</span>
                <strong className="about-metric-value">{sourceAssetCount}</strong>
                <span className="muted">
                  {documentCount} documents and {videoCount} videos
                </span>
              </div>
            </article>
            <article className="metric-card">
              <div className="stack">
                <span className="eyebrow">Service surface</span>
                <strong className="about-metric-value">11</strong>
                <span className="muted">API route groups, plus 3 background workers</span>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Why it exists</p>
          <h2>Built to close the gap between abstract quantum education and engineering reality</h2>
          <p>{courseSummary}</p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Problem</p>
            <h2>What most learners are missing</h2>
            <ul className="goal-list">
              <li>Too many quantum resources stay theoretical and disconnected from hardware limits, workflow design, and deployment tradeoffs.</li>
              <li>Static PDFs and proceedings are valuable, but they are difficult to interrogate, navigate, and retain without guided structure.</li>
              <li>Generic chat systems are not trustworthy for niche QC+AI topics when they cannot cite the actual source base.</li>
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">Response</p>
            <h2>What this platform changes</h2>
            <ul className="goal-list">
              <li>It organizes the corpus into a coherent module sequence with lesson-level summaries, notes, flashcards, quizzes, and projects.</li>
              <li>It keeps retrieval and Q&amp;A grounded in specific source evidence so learners can verify what the system says.</li>
              <li>It treats hybrid system design, optimization overhead, application evidence, and commercialization context as first-class teaching material.</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">What learners can do</p>
          <h2>Structured study, grounded retrieval, and applied practice in one platform</h2>
          <p>
            QC+AI Studio is designed as a full learning loop. Learners can move through the course path, interrogate the source material, practice,
            submit work, and monitor how their understanding is changing over time.
          </p>
        </div>
        <div className="module-grid">
          {platformPillars.map((pillar) => (
            <article className="panel" key={pillar.title}>
              <div className="stack">
                <p className="eyebrow">{pillar.eyebrow}</p>
                <h2>{pillar.title}</h2>
                <p>{pillar.description}</p>
                <div className="button-row">
                  <Link className="secondary-button" href={pillar.href}>
                    {pillar.action}
                  </Link>
                  {"secondaryHref" in pillar ? (
                    <Link className="secondary-button" href={pillar.secondaryHref}>
                      {pillar.secondaryAction}
                    </Link>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">How it is built</p>
          <h2>Full-stack architecture, not a single demo page</h2>
          <p>
            The platform combines a content assembly pipeline, grounded AI services, secure asset delivery, learner-state persistence, and a modern
            frontend delivery stack.
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

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Built with Codex</p>
          <h2>Human-directed, AI-assisted product engineering</h2>
          <p>
            OpenAI Codex was used across implementation, refinement, validation, infrastructure, and documentation work while the product owner kept
            scope, architecture, and acceptance decisions under direct control.
          </p>
        </div>
        <div className="module-grid">
          {CODEX_WORKSTREAMS.map((workstream) => (
            <article className="panel" key={workstream.title}>
              <div className="stack">
                <p className="eyebrow">{workstream.eyebrow}</p>
                <h2>{workstream.title}</h2>
                <p>{workstream.description}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Corpus and evidence</p>
          <h2>Grounded in curated references and local source assets</h2>
          <p>
            The public course is anchored in workshop proceedings, industry-use-case analysis, and lecture media rather than in generalized model
            pretraining alone.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <div className="stack">
              <p className="eyebrow">References</p>
              <h2>Core research corpus</h2>
              <ol className="reference-list">
                {COURSE_REFERENCES.map((reference, index) => (
                  <li key={reference} className="reference-item">
                    <span className="eyebrow">Reference {index + 1}</span>
                    <p>{reference}</p>
                  </li>
                ))}
              </ol>
            </div>
          </article>
          <article className="panel">
            <div className="stack">
              <p className="eyebrow">Asset inventory</p>
              <h2>Documents and lecture media</h2>
              <ul className="source-list compact">
                {sourceAssets.map((asset) => (
                  <li key={asset.id}>
                    <span>{asset.kind}</span>
                    <strong>{asset.title}</strong>
                    <p className="muted">{asset.description ?? asset.filename}</p>
                  </li>
                ))}
              </ul>
            </div>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">What makes it different</p>
          <h2>Designed as a serious learning product</h2>
          <p>
            QC+AI Studio is meant to be educationally useful, technically inspectable, and honest about how AI assistance was applied during the build.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <div className="stack">
              <p className="eyebrow">Differentiators</p>
              <h2>Why the platform stands apart</h2>
              <ul className="goal-list">
                {DIFFERENTIATORS.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </article>
          <article className="panel">
            <div className="stack">
              <p className="eyebrow">What was learned</p>
              <h2>Practical takeaways from the build</h2>
              <ul className="goal-list">
                {LESSONS_LEARNED.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </article>
        </div>
      </section>

      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Explore next</p>
          <h2>Study the curriculum or inspect the implementation</h2>
          <p>
            This platform is intended to work both as a real learner-facing product and as a transparent example of end-to-end human-directed,
            AI-assisted software engineering.
          </p>
        </div>
        <div className="button-row">
          <Link className="primary-button" href={startHref}>
            Enter the course
          </Link>
          <Link className="secondary-button" href="/syllabus">
            Open syllabus
          </Link>
          <Link className="secondary-button" href="/attribution">
            View attribution
          </Link>
          <a className="secondary-button" href={REPOSITORY_URL} rel="noreferrer" target="_blank">
            GitHub repository
          </a>
        </div>
      </section>
    </div>
  );
}
