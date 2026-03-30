import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { SimulationLabRenderer } from "@/components/simulation-gallery";
import type { SimulationModuleEntry, SimulationRecord } from "@/lib/simulations";

export function SimulationStudio({
  modules,
  simulation,
}: {
  modules: SimulationModuleEntry[];
  simulation: SimulationRecord;
}) {
  const activeModule =
    modules.find((module) => module.slug === simulation.moduleSlug) ?? modules[0] ?? null;

  if (!activeModule) {
    return null;
  }

  const currentIndex = activeModule.concepts.findIndex((item) => item.slug === simulation.slug);
  const previousSimulation = currentIndex > 0 ? activeModule.concepts[currentIndex - 1] : null;
  const nextSimulation =
    currentIndex >= 0 && currentIndex < activeModule.concepts.length - 1
      ? activeModule.concepts[currentIndex + 1]
      : null;
  const siblingSimulations = activeModule.concepts.filter((item) => item.slug !== simulation.slug);

  return (
    <div className="simulation-browser-shell simulation-detail-layout">
      <aside className="simulation-sidebar">
        <div className="simulation-sidebar-card">
          <p className="eyebrow">Simulation modules</p>
          <h2>Browse all sixteen labs</h2>
          <p>
            Every simulation now lives on its own route while staying grouped by module and connected
            to the broader curriculum path.
          </p>
        </div>

        <nav className="simulation-sidebar-list" aria-label="Simulation modules">
          {modules.map((module) => (
            <Link
              className={`simulation-sidebar-link ${module.slug === activeModule.slug ? "is-active" : ""}`}
              href={module.concepts[0]?.href ?? "/simulations"}
              key={module.slug}
            >
              <span className="simulation-sidebar-copy">
                <strong>Module {module.moduleNumber}</strong>
                <span>{module.title}</span>
              </span>
              <span className="simulation-sidebar-count">{module.simulationCount}</span>
            </Link>
          ))}
        </nav>

        <div className="simulation-sidebar-card" id="module-context">
          <p className="eyebrow">This module</p>
          <h2>{activeModule.title}</h2>
          <div className="simulation-nav-list">
            {activeModule.concepts.map((item) => (
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
        <section className="hero simulation-hero simulation-studio-hero">
          <div className="hero-copy">
            <Breadcrumbs
              items={[
                { label: "Home", href: "/" },
                { label: "Simulations", href: "/simulations" },
                { label: simulation.title },
              ]}
            />
            <p className="eyebrow">Simulation studio</p>
            <h1>{simulation.title}</h1>
            <p className="hero-text">{simulation.summary}</p>
            <p className="hero-text">{simulation.interaction}</p>

            <div className="simulation-badge-row">
              <span className="simulation-chip">{simulation.id}</span>
              <span className="simulation-chip tier">{simulation.difficulty}</span>
              <span className="simulation-chip available">Live lab</span>
              {simulation.correction ? <span className="simulation-chip corrected">Corrected</span> : null}
            </div>

            {simulation.formula ? <p className="simulation-formula">{simulation.formula}</p> : null}
            {simulation.correction ? <p className="simulation-callout">{simulation.correction}</p> : null}
            {simulation.emphasis ? <p className="simulation-emphasis">{simulation.emphasis}</p> : null}

            <div className="button-row">
              <Link className="secondary-button" href="/simulations">
                Back to simulations
              </Link>
              <Link className="secondary-button" href={`/modules/${simulation.moduleSlug}`}>
                Open module
              </Link>
              {previousSimulation ? (
                <Link className="secondary-button" href={previousSimulation.href}>
                  Previous lab
                </Link>
              ) : null}
              {nextSimulation ? (
                <Link className="primary-button" href={nextSimulation.href}>
                  Next lab
                </Link>
              ) : null}
            </div>
          </div>

          <div className="hero-panel">
            <p className="eyebrow">Module context</p>
            <h2>
              Module {simulation.moduleNumber}: {simulation.moduleTitle}
            </h2>
            <p className="muted">{simulation.moduleSummary}</p>
            <ul className="goal-list">
              <li>{activeModule.simulationCount} labs in this module.</li>
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
              This studio route isolates a single simulation so the learner can focus on one model,
              one control surface, and one explanatory framing at a time.
            </p>
          </div>
          <SimulationLabRenderer conceptId={simulation.id} />
        </section>

        <section className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Why this lab matters</p>
            <h2>Curriculum fit</h2>
            <p>
              {simulation.title} sits inside Module {simulation.moduleNumber} to reinforce the module&apos;s
              core teaching objective through direct manipulation rather than summary-only reading.
            </p>
            <p className="muted">{simulation.moduleSummary}</p>
          </article>

          <article className="panel emphasis-card">
            <p className="eyebrow">Keep exploring</p>
            <h2>More simulations in this module</h2>
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
