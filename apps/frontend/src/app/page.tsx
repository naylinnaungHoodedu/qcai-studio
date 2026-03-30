import type { Metadata } from "next";
import Link from "next/link";

import { ModuleCard } from "@/components/module-card";
import { PageErrorState } from "@/components/page-state";
import { StructuredData } from "@/components/structured-data";
import { fetchCourseOverview } from "@/lib/api";
import { COURSE_REFERENCES } from "@/lib/course-references";
import { buildPageMetadata } from "@/lib/metadata";
import { EXPANSION_ROADMAP, FEATURE_AVAILABILITY, RECENT_UPDATES } from "@/lib/public-status";
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
        <div className="curriculum-card-grid">
          {course.modules.map((module, index) => (
            <ModuleCard key={module.slug} module={module} moduleNumber={index + 1} />
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

      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Platform status</p>
          <h2>Feature availability is explicit on the public site</h2>
          <p>
            The live deployment now distinguishes what is available immediately, what runs in guest mode, and what depends on external identity or retrieval configuration.
          </p>
        </div>
        <div className="module-grid">
          {FEATURE_AVAILABILITY.map((item) => (
            <article className="panel" key={item.title}>
              <div className="panel-header">
                <div className="stack">
                  <p className="eyebrow">Availability</p>
                  <h2>{item.title}</h2>
                </div>
                <span className="status-pill">{item.status}</span>
              </div>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">What&apos;s new</p>
          <h2>Recent releases and visible next steps</h2>
          <p>
            The platform is compact by design right now. Public release notes and the expansion roadmap make that state visible instead of hiding it behind generic marketing language.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Recent updates</p>
            <h2>Recent public-facing releases</h2>
            <ul className="goal-list">
              {RECENT_UPDATES.map((item) => (
                <li key={item.title}>
                  <strong>{item.date}:</strong> {item.title}. {item.detail}
                </li>
              ))}
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">Expansion roadmap</p>
            <h2>What grows next</h2>
            <ul className="goal-list">
              {EXPANSION_ROADMAP.slice(0, 2).map((item) => (
                <li key={item.title}>
                  <strong>{item.title}:</strong> {item.detail}
                </li>
              ))}
            </ul>
            <div className="button-row">
              <Link className="primary-button" href="/whats-new">
                Open full changelog
              </Link>
              <Link className="secondary-button" href="/modules">
                Review the curriculum
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
              <h3>Browser-playable QC+AI simulation studio</h3>
              <p>Run the sixteen verified labs directly in the browser, inspect the corrected concept notes, and review the deeper rollout path for persistence and analytics.</p>
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
