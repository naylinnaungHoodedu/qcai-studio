"use client";

import Link from "next/link";
import { useState } from "react";

import type { SimulationModuleEntry, SimulationRecord } from "@/lib/simulations";

function SimulationLaunchCard({ simulation }: { simulation: SimulationRecord }) {
  return (
    <article className="simulation-launch-card">
      <div className="simulation-card-preview">
        <div className="simulation-badge-row">
          <span className="simulation-chip">{simulation.id}</span>
          <span className="simulation-chip tier">{simulation.difficulty}</span>
          <span className="simulation-chip available">Live lab</span>
          {simulation.correction ? <span className="simulation-chip corrected">Corrected</span> : null}
        </div>
        <strong>{simulation.title}</strong>
        <p>{simulation.interaction}</p>
      </div>

      <div className="stack">
        <p>{simulation.summary}</p>
        {simulation.formula ? <p className="simulation-formula">{simulation.formula}</p> : null}
      </div>

      <div className="button-row">
        <Link className="primary-button" href={simulation.href}>
          Launch simulation
        </Link>
        <Link className="secondary-button" href={`/modules/${simulation.moduleSlug}`}>
          Open module
        </Link>
      </div>
    </article>
  );
}

export function SimulationBrowser({
  modules,
  initialModuleSlug,
}: {
  modules: SimulationModuleEntry[];
  initialModuleSlug?: string;
}) {
  const [activeModuleSlug, setActiveModuleSlug] = useState(initialModuleSlug ?? modules[0]?.slug ?? "");
  const activeModule =
    modules.find((module) => module.slug === activeModuleSlug) ?? modules[0] ?? null;

  if (!activeModule) {
    return null;
  }

  const firstSimulation = activeModule.concepts[0] ?? null;

  return (
    <div className="simulation-browser-shell">
      <aside className="simulation-sidebar">
        <div className="simulation-sidebar-card">
          <p className="eyebrow">Simulation subjects</p>
          <h2>Six curriculum-aligned tracks</h2>
          <p>
            Switch between modules to browse the full sixteen-lab simulation program without keeping
            every lab open on one page.
          </p>
        </div>

        <div className="simulation-sidebar-list" role="tablist" aria-label="Simulation modules">
          {modules.map((module) => (
            <button
              aria-pressed={module.slug === activeModule.slug}
              className={`simulation-sidebar-button ${module.slug === activeModule.slug ? "is-active" : ""}`}
              key={module.slug}
              onClick={() => setActiveModuleSlug(module.slug)}
              type="button"
            >
              <span className="simulation-sidebar-copy">
                <strong>Module {module.moduleNumber}</strong>
                <span>{module.title}</span>
              </span>
              <span className="simulation-sidebar-count">{module.simulationCount}</span>
            </button>
          ))}
        </div>
      </aside>

      <div className="simulation-browser-main">
        <section className="panel simulation-subject-hero" id={`module-${activeModule.slug}`}>
          <div className="simulation-subject-copy">
            <p className="eyebrow">Module {activeModule.moduleNumber}</p>
            <h2>{activeModule.title}</h2>
            <p>{activeModule.summary}</p>
          </div>

          <div className="simulation-metric-grid">
            <article className="simulation-metric-tile">
              <span className="eyebrow">Simulations</span>
              <strong>{activeModule.simulationCount}</strong>
              <p>Dedicated labs separated into individual routes.</p>
            </article>
            <article className="simulation-metric-tile">
              <span className="eyebrow">First launch</span>
              <strong>{firstSimulation?.id ?? "--"}</strong>
              <p>Suggested starting point for this module.</p>
            </article>
            <article className="simulation-metric-tile">
              <span className="eyebrow">Availability</span>
              <strong>Live</strong>
              <p>Each lab opens as its own simulation studio page.</p>
            </article>
          </div>

          <div className="button-row">
            {firstSimulation ? (
              <Link className="primary-button" href={firstSimulation.href}>
                Launch first simulation
              </Link>
            ) : null}
            <Link className="secondary-button" href={`/modules/${activeModule.slug}`}>
              Open module
            </Link>
          </div>
        </section>

        <div className="simulation-launch-grid">
          {activeModule.concepts.map((simulation) => (
            <SimulationLaunchCard key={simulation.slug} simulation={simulation} />
          ))}
        </div>
      </div>
    </div>
  );
}
