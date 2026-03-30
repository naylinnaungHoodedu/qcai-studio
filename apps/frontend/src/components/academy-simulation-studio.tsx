import type { CSSProperties } from "react";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { AcademySimulationLabRenderer } from "@/components/academy-simulation-labs";
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

export function AcademySimulationStudio({
  simulation,
  subject,
  subjects,
  subjectSimulations,
}: {
  simulation: AcademySimulationRecord;
  subject: AcademySubjectRecord;
  subjects: AcademySubjectRecord[];
  subjectSimulations: AcademySimulationRecord[];
}) {
  const accentStyle = buildAccentStyle(subject.accentColor);
  const currentIndex = subjectSimulations.findIndex((item) => item.slug === simulation.slug);
  const previousSimulation = currentIndex > 0 ? subjectSimulations[currentIndex - 1] : null;
  const nextSimulation =
    currentIndex >= 0 && currentIndex < subjectSimulations.length - 1
      ? subjectSimulations[currentIndex + 1]
      : null;
  const siblingSimulations = subjectSimulations.filter((item) => item.slug !== simulation.slug);

  return (
    <div className="simulation-browser-shell academy-browser-shell simulation-detail-layout" style={accentStyle}>
      <aside className="simulation-sidebar">
        <div className="simulation-sidebar-card academy-sidebar-card">
          <p className="eyebrow">Simulation subjects</p>
          <h2>Browse all academy tracks</h2>
          <p>
            Each subject stays grouped by topic while every lab opens as its own dedicated studio
            surface.
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

        <div className="simulation-sidebar-card academy-sidebar-card" id="subject-context">
          <p className="eyebrow">This subject</p>
          <h2>{subject.title}</h2>
          <div className="simulation-nav-list">
            {subjectSimulations.map((item) => (
              <Link
                className={`simulation-nav-link ${item.slug === simulation.slug ? "is-active" : ""}`}
                href={item.href}
                key={item.slug}
              >
                <span className="simulation-chip">{item.id}</span>
                <span>{item.title}</span>
              </Link>
            ))}
          </div>
        </div>
      </aside>

      <div className="page-stack simulation-browser-main">
        <section className="hero simulation-hero academy-subject-hero simulation-studio-hero" style={accentStyle}>
          <div className="hero-copy">
            <Breadcrumbs
              items={[
                { label: "Home", href: "/" },
                { label: "Simulations", href: "/simulations" },
                { label: subject.title, href: subject.href },
                { label: simulation.title },
              ]}
            />
            <p className="eyebrow">Simulation studio</p>
            <div className="academy-hero-heading">
              <span className="academy-preview-icon large">{subject.iconLabel}</span>
              <div className="stack">
                <h1>{simulation.title}</h1>
                <p className="hero-text">{simulation.summary}</p>
                <p className="hero-text">{simulation.description}</p>
              </div>
            </div>

            <div className="simulation-badge-row">
              <span className="simulation-chip">{simulation.id}</span>
              <span className="simulation-chip tier">{simulation.difficulty}</span>
              <span className="academy-difficulty-pill">{subject.title}</span>
              <span className="simulation-chip available">Live lab</span>
            </div>

            {simulation.formula ? <p className="simulation-formula">{simulation.formula}</p> : null}

            <div className="button-row">
              <Link className="secondary-button" href={subject.href}>
                Back to subject
              </Link>
              <Link className="secondary-button" href="/simulations">
                Back to all simulations
              </Link>
              {previousSimulation ? (
                <Link className="secondary-button" href={previousSimulation.href}>
                  Previous lab
                </Link>
              ) : null}
              {nextSimulation ? (
                <Link className="academy-primary-button" href={nextSimulation.href} style={accentStyle}>
                  Next lab
                </Link>
              ) : null}
            </div>
          </div>

          <div className="hero-panel">
            <p className="eyebrow">Subject context</p>
            <h2>{subject.title}</h2>
            <p className="muted">{subject.summary}</p>
            <ul className="goal-list">
              <li>{subject.simulationCount} labs in this subject.</li>
              <li>Difficulty: {simulation.difficulty}.</li>
              <li>Dedicated route: {simulation.href}.</li>
            </ul>
          </div>
        </section>

        <section className="section-block">
          <div className="section-heading">
            <p className="eyebrow">Live lab</p>
            <h2>Interactive simulation workspace</h2>
            <p>
              These academy-style labs are designed as compact, browser-playable teaching surfaces:
              enough interaction to make the core idea legible, without pretending to be a full research
              workbench.
            </p>
          </div>
          <AcademySimulationLabRenderer simulation={simulation} />
        </section>

        <section className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">What this teaches</p>
            <h2>Core learning frame</h2>
            <p>{simulation.description}</p>
            <p className="muted">{simulation.summary}</p>
          </article>

          <article className="panel emphasis-card">
            <p className="eyebrow">Keep exploring</p>
            <h2>More labs in this subject</h2>
            <div className="simulation-nav-list">
              {siblingSimulations.map((item) => (
                <Link className="simulation-nav-link" href={item.href} key={item.slug}>
                  <span className="simulation-chip">{item.id}</span>
                  <span>{item.title}</span>
                </Link>
              ))}
            </div>
          </article>
        </section>
      </div>
    </div>
  );
}
