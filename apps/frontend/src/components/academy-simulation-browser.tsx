import type { CSSProperties } from "react";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import type {
  AcademySimulationRecord,
  AcademySubjectRecord,
} from "@/lib/academy-simulations";

function buildAccentStyle(color: string): CSSProperties {
  return {
    ["--academy-accent" as string]: color,
    ["--academy-accent-soft" as string]: `${color}20`,
    ["--academy-accent-strong" as string]: `${color}40`,
  };
}

function difficultyCounts(subject: AcademySubjectRecord) {
  return {
    beginner: subject.simulations.filter((simulation) => simulation.difficulty === "Beginner").length,
    intermediate: subject.simulations.filter((simulation) => simulation.difficulty === "Intermediate")
      .length,
    advanced: subject.simulations.filter((simulation) => simulation.difficulty === "Advanced").length,
  };
}

export function AcademySimulationCard({
  simulation,
  showSubjectLink = false,
}: {
  simulation: AcademySimulationRecord;
  showSubjectLink?: boolean;
}) {
  const accentStyle = buildAccentStyle(simulation.subjectAccentColor);

  return (
    <article className="academy-simulation-card" style={accentStyle}>
      <div className="academy-simulation-preview">
        <div className="simulation-badge-row">
          <span className="simulation-chip">{simulation.id}</span>
          <span className="simulation-chip tier">{simulation.difficulty}</span>
          <span className="academy-difficulty-pill">{simulation.subjectTitle}</span>
        </div>

        <div className="academy-preview-heading">
          <span className="academy-preview-icon">{simulation.subjectIconLabel}</span>
          <div className="stack">
            <strong>{simulation.title}</strong>
            <p>{simulation.tagline}</p>
          </div>
        </div>

        <div className="academy-preview-metrics">
          <article className="academy-preview-metric">
            <span className="eyebrow">Mode</span>
            <strong>Interactive</strong>
          </article>
          <article className="academy-preview-metric">
            <span className="eyebrow">Track</span>
            <strong>{simulation.subjectIconLabel}</strong>
          </article>
          <article className="academy-preview-metric">
            <span className="eyebrow">Level</span>
            <strong>{simulation.difficulty}</strong>
          </article>
        </div>
      </div>

      <div className="academy-card-copy">
        <p className="eyebrow">{simulation.subjectTitle}</p>
        <h3>{simulation.title}</h3>
        <p>{simulation.summary}</p>
        {simulation.formula ? <p className="simulation-formula">{simulation.formula}</p> : null}

        <div className="button-row">
          <Link className="academy-primary-button" href={simulation.href} style={accentStyle}>
            Launch simulation
          </Link>
          {showSubjectLink ? (
            <Link className="secondary-button" href={simulation.subjectHref}>
              Open subject
            </Link>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function AcademySubjectCatalog({ subjects }: { subjects: AcademySubjectRecord[] }) {
  return (
    <div className="academy-subject-grid">
      {subjects.map((subject) => {
        const accentStyle = buildAccentStyle(subject.accentColor);
        const firstSimulation = subject.simulations[0];
        const firstSimulationHref = firstSimulation
          ? `/simulations/subjects/${subject.slug}/${firstSimulation.slug}`
          : subject.href;

        return (
          <article className="academy-subject-card" key={subject.slug} style={accentStyle}>
            <div className="academy-subject-card-header">
              <span className="academy-preview-icon">{subject.iconLabel}</span>
              <div className="stack">
                <p className="eyebrow">{subject.eyebrow}</p>
                <h3>{subject.title}</h3>
              </div>
            </div>

            <p>{subject.summary}</p>

            <div className="academy-subject-card-list">
              {subject.simulations.slice(0, 3).map((simulation) => (
                <div className="academy-subject-card-item" key={simulation.slug}>
                  <strong>{simulation.title}</strong>
                  <span>{simulation.difficulty}</span>
                </div>
              ))}
            </div>

            <div className="academy-subject-card-footer">
              <span className="academy-difficulty-pill">{subject.simulationCount} simulations</span>
              <div className="button-row">
                <Link className="academy-primary-button" href={firstSimulationHref} style={accentStyle}>
                  Launch first lab
                </Link>
                <Link className="secondary-button" href={subject.href}>
                  Explore subject
                </Link>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

export function AcademySubjectBrowser({
  subject,
  subjects,
  subjectSimulations,
}: {
  subject: AcademySubjectRecord;
  subjects: AcademySubjectRecord[];
  subjectSimulations: AcademySimulationRecord[];
}) {
  const accentStyle = buildAccentStyle(subject.accentColor);
  const counts = difficultyCounts(subject);
  const firstSimulation = subjectSimulations[0] ?? null;

  return (
    <div className="simulation-browser-shell academy-browser-shell" style={accentStyle}>
      <aside className="simulation-sidebar">
        <div className="simulation-sidebar-card academy-sidebar-card">
          <p className="eyebrow">Simulation modules</p>
          <h2>Browse all eighteen labs</h2>
          <p>
            Each subject now has its own accent, its own launch cards, and its own set of dedicated
            simulation studios.
          </p>
        </div>

        <nav className="simulation-sidebar-list" aria-label="Simulation subjects">
          {subjects.map((item) => (
            <Link
              className={`simulation-sidebar-link ${item.slug === subject.slug ? "is-active" : ""}`}
              href={item.href}
              key={item.slug}
            >
              <span className="simulation-sidebar-copy">
                <strong>{item.title}</strong>
                <span>{item.simulationCount} interactive labs</span>
              </span>
              <span className="simulation-sidebar-count">{item.simulationCount}</span>
            </Link>
          ))}
        </nav>
      </aside>

      <div className="simulation-browser-main">
        <section className="hero simulation-hero academy-subject-hero" style={accentStyle}>
          <div className="hero-copy">
            <Breadcrumbs
              items={[
                { label: "Home", href: "/" },
                { label: "Simulations", href: "/simulations" },
                { label: subject.title },
              ]}
            />
            <p className="eyebrow">{subject.eyebrow}</p>
            <div className="academy-hero-heading">
              <span className="academy-preview-icon large">{subject.iconLabel}</span>
              <div className="stack">
                <h1>{subject.title}</h1>
                <p className="hero-text">{subject.summary}</p>
              </div>
            </div>
            <div className="button-row">
              {firstSimulation ? (
                <Link className="academy-primary-button" href={firstSimulation.href} style={accentStyle}>
                  Launch first simulation
                </Link>
              ) : null}
              <Link className="secondary-button" href="/simulations">
                Back to all simulations
              </Link>
            </div>
          </div>

          <div className="analytics-metric-grid">
            <article className="metric-card">
              <span className="eyebrow">Simulations</span>
              <strong className="about-metric-value">{subject.simulationCount}</strong>
              <p>All labs in this subject now open on individual routes.</p>
            </article>
            <article className="metric-card">
              <span className="eyebrow">Beginner</span>
              <strong className="about-metric-value">{counts.beginner}</strong>
              <p>Foundational visual-first labs for rapid entry.</p>
            </article>
            <article className="metric-card">
              <span className="eyebrow">Intermediate</span>
              <strong className="about-metric-value">{counts.intermediate}</strong>
              <p>Hands-on control surfaces for protocol and systems reasoning.</p>
            </article>
            <article className="metric-card">
              <span className="eyebrow">Advanced</span>
              <strong className="about-metric-value">{counts.advanced}</strong>
              <p>Higher-complexity labs that reveal structure and tradeoffs directly.</p>
            </article>
          </div>
        </section>

        <div className="academy-launch-grid">
          {subjectSimulations.map((simulation) => (
            <AcademySimulationCard key={simulation.slug} showSubjectLink={false} simulation={simulation} />
          ))}
        </div>
      </div>
    </div>
  );
}
