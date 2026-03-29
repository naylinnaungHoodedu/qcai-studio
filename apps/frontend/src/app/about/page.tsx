import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { fetchCourseOverview } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { COURSE_SCOPE_NOTE, ENGINEERING_READING_NOTES, INDUSTRY_METHOD_NOTE } from "@/lib/public-course";
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

export const metadata: Metadata = buildPageMetadata({
  title: "About the QC+AI Learning Platform",
  description:
    "Learn what QC+AI Studio is, why it was built, how the curriculum is curated, and how the live platform is engineered and reviewed.",
  path: "/about",
});

export default async function AboutPage() {
  const course = await fetchCourseOverview().catch(() => null);
  const sourceAssets = course?.source_assets.length ? course.source_assets : FALLBACK_SOURCE_ASSETS;
  const moduleCount = course?.modules.length ?? 6;
  const lessonCount = course?.modules.reduce((count, module) => count + module.lesson_slugs.length, 0) ?? 7;
  const videoCount = sourceAssets.filter((asset) => asset.kind.toLowerCase() === "video").length || 3;
  const documentCount = Math.max(sourceAssets.length - videoCount, 0);
  const structuredData = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "QC+AI Studio",
    url: `${SITE_URL}/about`,
    founder: OWNER_NAME,
    email: CONTACT_EMAIL,
    description:
      "QC+AI Studio is a source-grounded learning platform for quantum computing and AI built around hybrid-system design, hardware realism, and transparent public evaluation.",
  };

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
