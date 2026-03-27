import type { Metadata } from "next";
import Link from "next/link";

import { ModuleCard } from "@/components/module-card";
import { PageErrorState } from "@/components/page-state";
import { fetchCourseOverview } from "@/lib/api";
import { COURSE_REFERENCES } from "@/lib/course-references";
import { buildPageMetadata } from "@/lib/metadata";

export const metadata: Metadata = buildPageMetadata({
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
  const startHref = course.modules[0] ? `/modules/${course.modules[0].slug}` : "/syllabus";

  return (
    <div className="page-stack">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Quantum Hardware Perspective</p>
          <h1>Learn QC+AI through the realities of superconducting hardware and hybrid system design.</h1>
          <p className="hero-text">
            This course is built from the local QC+AI research and industry-use-case materials. It treats routing, noise, qubit scarcity,
            optimization reformulation, hybrid orchestration, application-specific evidence, and commercialization context as first-class teaching objects.
          </p>
          <div className="button-row">
            <Link className="primary-button" href={startHref}>
              Start with the course path
            </Link>
            <Link className="secondary-button" href="/dashboard">
              Open analytics hub
            </Link>
            <Link className="secondary-button" href="/syllabus">
              View syllabus
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
            <h2>References</h2>
            <ol className="reference-list">
              {COURSE_REFERENCES.map((reference, index) => (
                <li key={reference} className="reference-item">
                  <span className="eyebrow">Reference {index + 1}</span>
                  <p>{reference}</p>
                </li>
              ))}
            </ol>
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
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Adaptive Learning</p>
          <h2>Analytics, coaching, and skill-gap intelligence</h2>
          <p>
            The dashboard now tracks progress, focus, motivation, adaptive pacing, target-role gaps, and AI-generated
            next steps from the evidence you create across lessons, games, and projects.
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
              <p>Build practical QC+AI deliverables, get live AI draft feedback, and review peers against technical rubrics.</p>
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
          <p className="eyebrow">Interactive Games</p>
          <h2>Practice through competition and construction</h2>
          <p>
            Two new game modes extend the course beyond reading and quizzes: a live AI-and-quantum battle arena and a
            drag-and-drop dependency builder for engineering microlearning.
          </p>
        </div>
        <div className="lesson-list">
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
