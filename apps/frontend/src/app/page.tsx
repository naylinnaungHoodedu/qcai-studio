import type { Metadata } from "next";
import Link from "next/link";

import { ModuleCard } from "@/components/module-card";
import { PageErrorState } from "@/components/page-state";
import { StructuredData } from "@/components/structured-data";
import { fetchCourseOverview } from "@/lib/api";
import { COURSE_REFERENCES } from "@/lib/course-references";
import { buildPageMetadata } from "@/lib/metadata";
import { COURSE_SCOPE_NOTE, GUEST_MODE_NOTES } from "@/lib/public-course";
import { SITE_URL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Quantum Computing and AI Course",
  description:
    "Hardware-constrained quantum computing and AI learning, grounded in local proceedings, lesson scaffolds, and industry use cases.",
  path: "/",
});

export default async function HomePage() {
  const course = await fetchCourseOverview().catch(() => null);
  if (!course) {
    return (
      <PageErrorState
        title="Course overview is temporarily unavailable"
        detail="The public course data API did not respond cleanly for the homepage."
      />
    );
  }
  const totalLessons = course.modules.reduce((count, module) => count + module.lesson_slugs.length, 0);
  const videoCount = course.source_assets.filter((asset) => asset.kind === "video").length;
  const startHref = course.modules[0] ? `/modules/${course.modules[0].slug}` : "/modules";
  const structuredData = {
    "@context": "https://schema.org",
    "@type": "Course",
    name: course.title,
    description: course.summary,
    provider: {
      "@type": "Organization",
      name: "QC+AI Studio",
      url: SITE_URL,
    },
    educationalCredentialAwarded: "Course completion is currently portfolio-based; no certificate is issued yet.",
    numberOfCredits: 0,
    hasCourseInstance: {
      "@type": "CourseInstance",
      courseMode: "online",
      url: SITE_URL,
    },
  };

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="home-course-jsonld" />
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Quantum Hardware Perspective</p>
          <h1>Learn QC+AI through the realities of superconducting hardware and hybrid system design.</h1>
          <p className="hero-text">
            This course is built from the local QC+AI research and industry-use-case materials. It treats routing, noise, qubit scarcity,
            optimization reformulation, hybrid orchestration, application-specific evidence, and commercialization context as first-class teaching objects.
          </p>
          <p className="hero-text">{COURSE_SCOPE_NOTE}</p>
          <div className="button-row">
            <Link className="primary-button" href={startHref}>
              Start with the course path
            </Link>
            <Link className="secondary-button" href="/modules">
              Browse modules
            </Link>
            <Link className="secondary-button" href="/simulations">
              Explore simulations
            </Link>
            <Link className="secondary-button" href="/dashboard">
              Open guest dashboard
            </Link>
            <Link className="secondary-button" href="/search">
              Search materials
            </Link>
          </div>
        </div>
        <div className="hero-grid">
          <div className="hero-panel">
            <p className="eyebrow">Course footprint</p>
            <h2>
              {course.modules.length} modules, {totalLessons} lessons
            </h2>
            <p className="muted">
              {course.source_assets.length} source assets, including {videoCount} video lessons and curated document synthesis.
            </p>
          </div>
          <div className="hero-panel">
            <p className="eyebrow">Public access</p>
            <h2>What you can try right now</h2>
            <ul className="goal-list">
              {GUEST_MODE_NOTES.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Course Architecture</p>
          <h2>{course.title}</h2>
          <p>{course.summary}</p>
        </div>
        <div className="module-grid">
          {course.modules.map((module) => (
            <ModuleCard key={module.slug} module={module} />
          ))}
        </div>
        <div className="button-row">
          <Link className="secondary-button" href="/modules">
            Open curriculum hub
          </Link>
          <Link className="secondary-button" href="/syllabus">
            View syllabus
          </Link>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Corpus and evidence</p>
          <h2>Grounded in curated research and lecture material</h2>
          <p>
            The public platform is anchored in a compact local corpus. References remain visible so learners and evaluators can inspect the evidentiary base behind the curriculum.
          </p>
        </div>
        <ol className="reference-list">
          {COURSE_REFERENCES.map((reference, index) => (
            <li key={reference} className="reference-item">
              <span className="eyebrow">Reference {index + 1}</span>
              <p>{reference}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Adaptive Learning</p>
          <h2>Analytics, coaching, and applied project work</h2>
          <p>
            The platform extends beyond lesson reading. Learners can monitor progress, submit portfolio-style work, and stress-test recall through interactive study surfaces.
          </p>
        </div>
        <div className="lesson-list">
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Dashboard</p>
              <h3>Powerful analytics dashboard</h3>
              <p>Track momentum, focus, motivation, readiness for target roles, and the next adaptive steps.</p>
            </div>
            <div className="lesson-actions">
              <Link className="primary-button" href="/dashboard">
                View insights
              </Link>
            </div>
          </article>
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Projects</p>
              <h3>Hands-on projects and peer review</h3>
              <p>Build practical QC+AI deliverables, get live AI draft feedback, and review peers against explicit technical rubrics.</p>
            </div>
            <div className="lesson-actions">
              <Link className="primary-button" href="/projects">
                Open project studio
              </Link>
            </div>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Interactive practice</p>
          <h2>Competition and construction modes</h2>
          <p>
            Arena and Builder keep the course from collapsing into static reading. They create additional recall, comparison, and systems-thinking loops for returning learners.
          </p>
        </div>
        <div className="lesson-list">
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Simulations</p>
              <h3>Verified QC+AI simulation roadmap</h3>
              <p>Inspect the sixteen-simulation catalog, corrected concept notes, and the implementation path for turning the course into a learn-by-doing studio.</p>
            </div>
            <div className="lesson-actions">
              <Link className="primary-button" href="/simulations">
                Open simulations
              </Link>
            </div>
          </article>
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Arena</p>
              <h3>AI &amp; Quantum Challenge Arena</h3>
              <p>Face ranked rivals or an adaptive bot across real-time AI/ML and quantum systems challenges.</p>
            </div>
            <div className="lesson-actions">
              <Link className="primary-button" href="/arena">
                Enter arena
              </Link>
            </div>
          </article>
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Builder</p>
              <h3>Microlearning Drag-and-Drop Builder</h3>
              <p>Assemble dependency graphs, unlock the next circuit, and share completed learning maps to the feed.</p>
            </div>
            <div className="lesson-actions">
              <Link className="primary-button" href="/builder">
                Open builder
              </Link>
            </div>
          </article>
        </div>
      </section>
    </div>
  );
}
