import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { SimulationGallery } from "@/components/simulation-gallery";
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
            This public page now hosts the March 2026 QC+AI simulation library as a live browser surface: sixteen verified simulations, inline corrections, runnable teaching prototypes, and the architecture notes needed to harden them into fully persisted product features.
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
            The simulation program is now public, inspectable, and runnable in the browser. That still does not mean the deeper platform layer is complete: simulation sessions are not yet persisted into learner history, and analytics or arena variants are still future engineering work. The value of this page is that the interaction layer and the remaining implementation boundaries are both explicit.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Current status</p>
            <h2>Live browser prototypes, deeper platform work next</h2>
            <ul className="goal-list">
              <li>All sixteen simulations now have playable browser labs grouped by module and corrected where needed.</li>
              <li>The teaching model still requires source citation, saveable state, and arena-compatible variants as the next platform layer.</li>
              <li>The next engineering step is to persist session state and embed the strongest labs directly into lesson flow.</li>
            </ul>
          </article>
          <article className="panel emphasis-card">
            <p className="eyebrow">Prototype anchor</p>
            <h2>{SIMULATION_FIRST_STEP.title}</h2>
            <p>{SIMULATION_FIRST_STEP.summary}</p>
            <p className="muted">
              {SIMULATION_FIRST_STEP.id} remains the clearest thesis statement for the simulation layer because it is mathematically compact, easy to explain, and directly tied to why NISQ realism matters.
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
          <h2>Sixteen verified simulations mapped to the curriculum and playable in the browser</h2>
          <p>
            The catalog is organized by module so evaluators can see exactly how the simulation layer reinforces the current lesson path. Concepts marked corrected include explicit change notes, not silent edits, and each card now opens a browser-playable lab.
          </p>
        </div>
        <SimulationGallery modules={SIMULATION_MODULES} />
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
            The simulations page now exposes both the product direction and a working browser layer. The next useful step is to read the relevant module, inspect the existing lesson path, and decide which labs should be embedded directly into lessons with persistence, citations, and analytics.
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
