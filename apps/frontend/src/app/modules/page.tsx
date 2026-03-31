import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { ModuleCard } from "@/components/module-card";
import { PageErrorState } from "@/components/page-state";
import { StructuredData } from "@/components/structured-data";
import { fetchCourseOverview } from "@/lib/api";
import { formatModuleLabel } from "@/lib/module-labels";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { COMPLETION_SIGNAL_NOTES, EXPANSION_ROADMAP } from "@/lib/public-status";
import {
  CURRICULUM_ARCHITECTURE_STAGES,
  COURSE_SCOPE_NOTE,
  ENGINEERING_READING_NOTES,
  GUEST_MODE_NOTES,
  INDUSTRY_METHOD_NOTE,
  PREREQUISITES,
  PROJECT_PREVIEW,
  TARGET_AUDIENCE,
} from "@/lib/public-course";
import { SITE_URL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Quantum Computing and AI Modules",
  description:
    "Browse the QC+AI curriculum hub, prerequisites, public project rubrics, methodological notes, and the full module path.",
  path: "/modules",
});

export default async function ModulesLandingPage() {
  const course = await fetchCourseOverview().catch(() => null);

  if (!course) {
    return (
      <PageErrorState
        title="The curriculum hub could not be loaded"
        detail="Public course structure data was unavailable for this request."
      />
    );
  }

  const totalLessons = course.modules.reduce((count, module) => count + module.lesson_slugs.length, 0);
  const firstModuleHref = course.modules[0] ? `/modules/${course.modules[0].slug}` : "/syllabus";
  const modulesBySlug = new Map(
    course.modules.map((module, index) => [module.slug, { module, moduleNumber: index + 1 }] as const),
  );
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "Course",
      name: course.title,
      description: course.summary,
      provider: {
        "@type": "Organization",
        name: "QC+AI Studio",
        url: SITE_URL,
      },
      url: `${SITE_URL}/modules`,
    },
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "Modules", path: "/modules" },
    ]),
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="modules-jsonld" />
      <section className="hero about-hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Modules" },
            ]}
          />
          <p className="eyebrow">Curriculum hub</p>
          <h1>Study the QC+AI path before you commit to the full platform.</h1>
          <p className="hero-text">{COURSE_SCOPE_NOTE}</p>
          <p className="hero-text">
            This page makes the public learning contract explicit: who the course is for, what background helps, how the modules are sequenced, and how projects are judged.
          </p>
          <div className="button-row">
            <span className="status-pill in_progress">
              {formatModuleLabel(1)} to {formatModuleLabel(course.modules.length)}
            </span>
            <span className="status-pill">{totalLessons} lesson path</span>
          </div>
          <div className="button-row">
            <Link className="primary-button" href={firstModuleHref}>
              Start with module 1
            </Link>
            <Link className="secondary-button" href="/syllabus">
              Open syllabus
            </Link>
            <Link className="secondary-button" href="/projects">
              Review project studio
            </Link>
          </div>
        </div>
        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Modules</span>
            <strong className="about-metric-value">{course.modules.length}</strong>
            <p>Compact module sequence with public summaries and source highlights.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Lessons</span>
            <strong className="about-metric-value">{totalLessons}</strong>
            <p>Focused lesson set designed to lead into practice and project work quickly.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Projects</span>
            <strong className="about-metric-value">{PROJECT_PREVIEW.length}</strong>
            <p>Publicly visible deliverables with explicit rubrics and linked lessons.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Access</span>
            <strong className="about-metric-value">Guest</strong>
            <p>Public study flows work in-browser before persistent identity is configured.</p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Audience and prerequisites</p>
          <h2>Who this is for</h2>
          <p>
            The course assumes technical maturity, but it does not assume that you already work in production quantum computing. It is designed to be approachable for advanced learners who can reason about systems, tradeoffs, and evidence.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Best fit</p>
            <h2>Intended learners</h2>
            <ul className="goal-list">
              {TARGET_AUDIENCE.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">Before you begin</p>
            <h2>Helpful prerequisites</h2>
            <ul className="goal-list">
              {PREREQUISITES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Curriculum architecture</p>
          <h2>Eleven modules arranged as a staged learning progression</h2>
          <p>
            The curriculum now reads as a progression rather than a historical split. Each stage below explains why the modules appear where they do, what intellectual move they ask from the learner, and how the overall path advances from hardware realism to specialization.
          </p>
        </div>
        <div className="stack">
          {CURRICULUM_ARCHITECTURE_STAGES.map((stage) => {
            const stageModules = stage.moduleSlugs
              .map((slug) => modulesBySlug.get(slug))
              .filter((entry): entry is { module: (typeof course.modules)[number]; moduleNumber: number } =>
                Boolean(entry),
              );

            if (!stageModules.length) {
              return null;
            }

            return (
              <div className="stack" key={stage.title}>
                <article className="panel">
                  <div className="section-heading">
                    <div className="button-row">
                      <span className="status-pill">{stage.moduleRange}</span>
                    </div>
                    <p className="eyebrow">Learning stage</p>
                    <h2>{stage.title}</h2>
                    <p>{stage.summary}</p>
                    <p className="muted">{stage.detail}</p>
                  </div>
                </article>
                <div className="curriculum-card-grid">
                  {stageModules.map(({ module, moduleNumber }) => (
                    <ModuleCard key={module.slug} module={module} moduleNumber={moduleNumber} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">How to read the course</p>
          <h2>Editorial guidance for technically skeptical learners</h2>
          <p>
            The strongest way to use this curriculum is to read it as a hybrid-systems studio. The point is not to memorize hype terms. The point is to understand where quantum components are plausibly useful, where they are not, and how evidence should be weighed.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Engineering interpretation</p>
            <h2>Three lenses to keep</h2>
            <ul className="goal-list">
              {ENGINEERING_READING_NOTES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article className="panel">
            <p className="eyebrow">Module 5 note</p>
            <h2>Industry-use-case methodology</h2>
            <p>{INDUSTRY_METHOD_NOTE}</p>
            <p className="muted">
              That module is still valuable, but it should be interpreted as an applied decision-making and commercialization lens, not as proof of broad quantum deployment maturity.
            </p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Assessment model</p>
          <h2>Public project rubrics and deliverables</h2>
          <p>
            Project work is part of the public platform, not hidden behind opaque claims. The current track uses portfolio-style deliverables and explicit rubrics rather than certificate-style grading.
          </p>
        </div>
        <div className="module-grid">
          {PROJECT_PREVIEW.map((project) => (
            <article className="panel" key={project.slug}>
              <div className="stack">
                <p className="eyebrow">Project brief</p>
                <h2>{project.title}</h2>
                <p>{project.deliverable}</p>
                <ul className="goal-list">
                  {project.rubric.map((criterion) => (
                    <li key={criterion}>{criterion}</li>
                  ))}
                </ul>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Expansion and completion</p>
          <h2>How the compact track grows from here</h2>
          <p>
            The public site already says this is not yet a fifteen-week semester. The next step is to make the growth path and the completion signal equally explicit.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Roadmap</p>
            <h2>Expansion path</h2>
            <ul className="goal-list">
              {EXPANSION_ROADMAP.map((item) => (
                <li key={item.title}>
                  <strong>{item.title}:</strong> {item.detail}
                </li>
              ))}
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">Completion signals</p>
            <h2>What learners can point to today</h2>
            <ul className="goal-list">
              {COMPLETION_SIGNAL_NOTES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <div className="button-row">
              <Link className="primary-button" href="/projects">
                Open project studio
              </Link>
              <Link className="secondary-button" href="/whats-new">
                Review the roadmap
              </Link>
            </div>
          </article>
        </div>
      </section>

      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Public access mode</p>
          <h2>What works before sign-in</h2>
          <p>
            The live deployment favors transparent public evaluation. A browser can enter guest mode immediately, while persistent identity remains a separate capability.
          </p>
        </div>
        <ul className="goal-list">
          {GUEST_MODE_NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
        <div className="button-row">
          <Link className="primary-button" href="/search">
            Open grounded search
          </Link>
          <Link className="secondary-button" href="/dashboard">
            Open guest dashboard
          </Link>
          <Link className="secondary-button" href="/account">
            Review guest access
          </Link>
        </div>
      </section>
    </div>
  );
}
