import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildPageMetadata } from "@/lib/metadata";
import {
  SIMULATION_ARCHITECTURE_NOTES,
  SIMULATION_ENDPOINTS,
  SIMULATION_FIRST_STEP,
  SIMULATION_FOUNDATION_CHECKLIST,
  SIMULATION_MODULES,
  SIMULATION_PHASES,
  SIMULATION_PRINCIPLES,
  SIMULATION_STACK_CHOICES,
  SIMULATION_STATUS_NOTE,
  SIMULATION_STATES,
  SIMULATION_TIERS,
  SIMULATION_VERIFIED_ITEMS,
} from "@/lib/simulations";
import { SITE_URL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Quantum Computing and AI Simulations",
  description:
    "Review the verified QC+AI simulation program, corrected concept designs, UX principles, implementation architecture, and phased roadmap.",
  path: "/simulations",
});

export default function SimulationsPage() {
  const concepts = SIMULATION_MODULES.flatMap((module) => module.concepts);
  const correctedCount = concepts.filter((concept) => concept.correction).length;
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: "QC+AI Studio simulations",
      description:
        "Verified simulation catalog and implementation roadmap for the QC+AI Studio learning platform.",
      url: `${SITE_URL}/simulations`,
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "Home",
          item: SITE_URL,
        },
        {
          "@type": "ListItem",
          position: 2,
          name: "Simulations",
          item: `${SITE_URL}/simulations`,
        },
      ],
    },
    {
      "@context": "https://schema.org",
      "@type": "ItemList",
      itemListOrder: "https://schema.org/ItemListOrderAscending",
      numberOfItems: concepts.length,
      itemListElement: concepts.map((concept, index) => ({
        "@type": "ListItem",
        position: index + 1,
        name: `${concept.id} ${concept.title}`,
      })),
    },
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="simulations-jsonld" />

      <section className="hero simulation-hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Simulations" },
            ]}
          />
          <p className="eyebrow">Simulation program</p>
          <h1>Verified QC+AI simulations designed to make the curriculum learn-by-doing.</h1>
          <p className="hero-text">
            This public page publishes the March 2026 simulation concept library for QC+AI Studio: sixteen verified simulations, inline corrections, the teaching model behind them, and the implementation path needed to bring them into the live product.
          </p>
          <p className="hero-text">{SIMULATION_STATUS_NOTE}</p>
          <div className="button-row">
            <a className="primary-button" href="#simulation-library">
              Review all 16 simulations
            </a>
            <a className="secondary-button" href="#implementation-roadmap">
              Open the roadmap
            </a>
            <Link className="secondary-button" href="/modules">
              Match them to modules
            </Link>
            <Link className="secondary-button" href="/projects">
              Inspect project flows
            </Link>
          </div>
        </div>

        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Concepts</span>
            <strong className="about-metric-value">{concepts.length}</strong>
            <p>Verified simulation concepts distributed across the six public modules.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Corrections</span>
            <strong className="about-metric-value">{correctedCount}</strong>
            <p>Concepts with explicit scientific or implementation corrections carried into the public design.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Principles</span>
            <strong className="about-metric-value">{SIMULATION_PRINCIPLES.length}</strong>
            <p>UX and pedagogy rules that keep the labs source-grounded and study-oriented.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Roadmap</span>
            <strong className="about-metric-value">{SIMULATION_PHASES.length}</strong>
            <p>Sequential implementation phases from foundation work to public demo polish.</p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Public framing</p>
          <h2>What this page claims, and what it does not claim</h2>
          <p>
            The simulation program is now public and inspectable. That improves transparency immediately, but it is not the same as claiming that every simulation is already embedded as a production interaction. The value of this page is that the roadmap, corrected concepts, and implementation boundaries are now explicit instead of hidden.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Current status</p>
            <h2>Verified design, phased implementation</h2>
            <ul className="goal-list">
              <li>The sixteen simulations are defined, grouped by module, and corrected where needed.</li>
              <li>The teaching model now requires source citation, saveable state, and arena-compatible variants.</li>
              <li>The next engineering step is to start with the simplest high-value public simulation rather than attempting the entire program at once.</li>
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">First priority</p>
            <h2>{SIMULATION_FIRST_STEP.title}</h2>
            <p>{SIMULATION_FIRST_STEP.summary}</p>
            <p className="muted">
              {SIMULATION_FIRST_STEP.id} is the best public teaser because it is mathematically compact, easy to explain, and directly tied to why NISQ realism matters.
            </p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Interaction model</p>
          <h2>Three tiers and three interface states</h2>
          <p>
            The program is intentionally mixed. Some simulations teach classification and architecture framing, some teach constrained behavior, and some expose quantitative physics or optimization tradeoffs. Every one of them should still move through explore, challenge, and explain states.
          </p>
        </div>
        <div className="module-grid">
          {SIMULATION_TIERS.map((tier) => (
            <article className="panel" key={tier.title}>
              <p className="eyebrow">Learning tier</p>
              <h2>{tier.title}</h2>
              <p>{tier.description}</p>
            </article>
          ))}
        </div>
        <div className="simulation-state-grid">
          {SIMULATION_STATES.map((item) => (
            <article className="simulation-state-card" key={item.state}>
              <p className="eyebrow">{item.state}</p>
              <h2>{item.visualTreatment}</h2>
              <p>{item.purpose}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block" id="simulation-library">
        <div className="section-heading">
          <p className="eyebrow">Concept library</p>
          <h2>Sixteen verified simulations mapped to the curriculum</h2>
          <p>
            The catalog is organized by module so evaluators can see exactly how the simulation layer reinforces the current lesson path. Concepts marked corrected include explicit change notes, not silent edits.
          </p>
        </div>
        <div className="simulation-module-list">
          {SIMULATION_MODULES.map((module) => (
            <article className="panel simulation-module-block" key={module.slug}>
              <div className="module-card-header">
                <div className="stack">
                  <p className="eyebrow">Module {module.moduleNumber}</p>
                  <h2>{module.title}</h2>
                  <p>{module.summary}</p>
                </div>
                <Link className="secondary-button inline-action" href={`/modules/${module.slug}`}>
                  Open module
                </Link>
              </div>

              <div className="simulation-card-grid">
                {module.concepts.map((concept) => (
                  <article className="simulation-card" key={concept.id}>
                    <div className="simulation-badge-row">
                      <span className="simulation-chip">{concept.id}</span>
                      <span className="simulation-chip tier">{concept.tier}</span>
                      {concept.correction ? <span className="simulation-chip corrected">Corrected</span> : null}
                    </div>
                    <h3>{concept.title}</h3>
                    <p>{concept.summary}</p>
                    <p className="muted">{concept.interaction}</p>
                    {concept.formula ? <p className="simulation-formula">{concept.formula}</p> : null}
                    {concept.correction ? <p className="simulation-callout">{concept.correction}</p> : null}
                    {concept.emphasis ? <p className="simulation-emphasis">{concept.emphasis}</p> : null}
                  </article>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Teaching rules</p>
          <h2>Principles that keep the simulation layer trustworthy</h2>
          <p>
            The design is not only about visual polish. These principles keep the simulations aligned with the source-grounded character of the platform and prevent them from becoming detached toy widgets.
          </p>
        </div>
        <div className="module-grid">
          {SIMULATION_PRINCIPLES.map((principle) => (
            <article className="panel" key={principle.title}>
              <p className="eyebrow">Principle</p>
              <h2>{principle.title}</h2>
              <p>{principle.summary}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Implementation architecture</p>
          <h2>What the simulation system needs technically</h2>
          <p>
            The existing product already has a credible foundation, but a real simulation layer needs state persistence, citation resolution, event analytics, and a disciplined browser-side rendering strategy.
          </p>
        </div>
        <div className="module-grid">
          {SIMULATION_ARCHITECTURE_NOTES.map((note) => (
            <article className="panel" key={note.title}>
              <p className="eyebrow">Architecture note</p>
              <h2>{note.title}</h2>
              <ul className="goal-list">
                {note.bullets.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            </article>
          ))}

          <article className="panel">
            <p className="eyebrow">Recommended stack choices</p>
            <h2>Browser-first simulation delivery</h2>
            <div className="simulation-detail-list">
              {SIMULATION_STACK_CHOICES.map((choice) => (
                <div className="simulation-detail-item" key={choice.requirement}>
                  <strong>{choice.requirement}</strong>
                  <p>{choice.choice}</p>
                  <p className="muted">{choice.rationale}</p>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <p className="eyebrow">API surface</p>
            <h2>New routes required for simulation state</h2>
            <div className="simulation-detail-list">
              {SIMULATION_ENDPOINTS.map((endpoint) => (
                <div className="simulation-detail-item" key={`${endpoint.method}-${endpoint.path}`}>
                  <strong>
                    {endpoint.method} {endpoint.path}
                  </strong>
                  <p>{endpoint.purpose}</p>
                  <p className="muted">{endpoint.extendsSurface}</p>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <p className="eyebrow">Phase 0 checklist</p>
            <h2>Foundation work that must exist before full rollout</h2>
            <ul className="goal-list">
              {SIMULATION_FOUNDATION_CHECKLIST.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      <section className="section-block" id="implementation-roadmap">
        <div className="section-heading">
          <p className="eyebrow">Roadmap</p>
          <h2>Six phases from foundation to public demo polish</h2>
          <p>
            The rollout sequence is intentionally staged. Phase 0 unlocks everything else. After that, the emphasis shifts from the clearest public demo to the strongest technical differentiators and then to full curriculum coverage.
          </p>
        </div>
        <div className="module-grid">
          {SIMULATION_PHASES.map((phase) => (
            <article className="panel" key={phase.phase}>
              <p className="eyebrow">Implementation phase</p>
              <h2>{phase.phase}</h2>
              <p>{phase.deliverables}</p>
              <p className="muted">{phase.priority}</p>
            </article>
          ))}
        </div>
        <div className="two-column-grid">
          <article className="panel emphasis-card">
            <p className="eyebrow">Most important next step</p>
            <h2>{SIMULATION_FIRST_STEP.id}</h2>
            <p>{SIMULATION_FIRST_STEP.summary}</p>
            <div className="button-row">
              <Link className="primary-button" href="/modules/nisq-hybrid-workflows">
                Open Module 1
              </Link>
              <Link className="secondary-button" href="/lessons/nisq-reality-overview">
                Open the NISQ lesson
              </Link>
            </div>
          </article>
          <article className="panel">
            <p className="eyebrow">Confirmed clean</p>
            <h2>Items that were verified and did not require correction</h2>
            <ul className="goal-list">
              {SIMULATION_VERIFIED_ITEMS.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        </div>
      </section>

      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Explore next</p>
          <h2>Use the curriculum pages to anchor the simulation roadmap</h2>
          <p>
            The simulations page now exposes the product direction clearly. The next useful step is to read the relevant module, inspect the existing lesson path, and then decide which simulation should become the first public interactive build.
          </p>
        </div>
        <div className="button-row">
          <Link className="primary-button" href="/modules">
            Open modules
          </Link>
          <Link className="secondary-button" href="/syllabus">
            Open syllabus
          </Link>
          <Link className="secondary-button" href="/about">
            Read product context
          </Link>
        </div>
      </section>
    </div>
  );
}
