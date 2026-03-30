import type { Metadata } from "next";
import Link from "next/link";

import { AcademySubjectCatalog } from "@/components/academy-simulation-browser";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { SimulationBrowser } from "@/components/simulation-browser";
import { StructuredData } from "@/components/structured-data";
import {
  ACADEMY_SIMULATION_RECORDS,
  ACADEMY_SUBJECT_RECORDS,
} from "@/lib/academy-simulations";
import { buildPageMetadata } from "@/lib/metadata";
import {
  SIMULATION_FIRST_STEP,
  SIMULATION_MODULE_ENTRIES,
  SIMULATION_PHASES,
  SIMULATION_PRINCIPLES,
  SIMULATION_RECORDS,
  SIMULATION_STATUS_NOTE,
} from "@/lib/simulations";
import { SITE_URL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Quantum Computing and AI Simulations",
  description:
    "Browse the expanded QC+AI simulation library: sixteen curriculum-aligned studios plus eighteen academy-style subject labs, all on dedicated routes.",
  path: "/simulations",
});

export default function SimulationsPage() {
  const correctedCount = SIMULATION_RECORDS.filter((concept) => concept.correction).length;
  const moduleCount = SIMULATION_MODULE_ENTRIES.length;
  const academySubjectCount = ACADEMY_SUBJECT_RECORDS.length;
  const academySimulationCount = ACADEMY_SIMULATION_RECORDS.length;
  const totalSimulationCount = SIMULATION_RECORDS.length + academySimulationCount;
  const recommendedSimulation =
    SIMULATION_RECORDS.find((simulation) => simulation.id === SIMULATION_FIRST_STEP.id) ??
    SIMULATION_RECORDS[0] ??
    null;
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: "QC+AI Studio simulations",
      description:
        "A separated simulation catalog with individual routes for all sixteen QC+AI browser labs.",
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
      numberOfItems: totalSimulationCount,
      itemListElement: [...SIMULATION_RECORDS, ...ACADEMY_SIMULATION_RECORDS].map((concept, index) => ({
        "@type": "ListItem",
        position: index + 1,
        name: concept.title,
        url: `${SITE_URL}${concept.href}`,
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
          <h1>Thirty-four QC+AI simulations, split across curriculum studios and subject labs.</h1>
          <p className="hero-text">
            The simulation layer now behaves like a real library instead of a single long document. The
            original sixteen course labs remain grouped by the six-module curriculum, and eighteen new
            academy-style labs now live in their own subject tracks and dedicated studio routes.
          </p>
          <p className="hero-text">{SIMULATION_STATUS_NOTE}</p>
          <div className="button-row">
            <a className="primary-button" href="#simulation-browser">
              Browse course studios
            </a>
            <a className="secondary-button" href="#academy-subjects">
              Browse academy subjects
            </a>
            <Link
              className="secondary-button"
              href={recommendedSimulation?.href ?? "/simulations"}
            >
              Launch the recommended first lab
            </Link>
            <Link className="secondary-button" href="/modules">
              Match labs to modules
            </Link>
          </div>
        </div>

        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Total labs</span>
            <strong className="about-metric-value">{totalSimulationCount}</strong>
            <p>Every simulation now opens on its own dedicated route.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Course studios</span>
            <strong className="about-metric-value">{SIMULATION_RECORDS.length}</strong>
            <p>The original curriculum-aligned sixteen-lab track remains intact.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Academy labs</span>
            <strong className="about-metric-value">{academySimulationCount}</strong>
            <p>Reference-inspired subjects now add topic-specific simulation tracks.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Subjects</span>
            <strong className="about-metric-value">{academySubjectCount}</strong>
            <p>Five subject families complement the six curriculum modules.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Modules</span>
            <strong className="about-metric-value">{moduleCount}</strong>
            <p>The catalog stays grouped by the six curriculum tracks.</p>
          </article>
        </div>
      </section>

      <section className="section-block" id="simulation-browser">
        <div className="section-heading">
          <p className="eyebrow">Separated catalog</p>
          <h2>Choose a module, then launch one simulation at a time</h2>
          <p>
            This browser keeps the module grouping visible while letting each lab stand on its own page,
            closer to a real simulation library than a single scroll-heavy gallery.
          </p>
        </div>
        <SimulationBrowser modules={SIMULATION_MODULE_ENTRIES} />
      </section>

      <section className="section-block" id="academy-subjects">
        <div className="section-heading">
          <p className="eyebrow">Additional subject tracks</p>
          <h2>Academy-style simulation subjects, each with its own dedicated lab pages</h2>
          <p>
            These new tracks follow the reference browsing pattern more closely: topic-based groupings,
            distinct accent systems, and launch cards that open one simulation studio at a time.
          </p>
        </div>
        <AcademySubjectCatalog subjects={ACADEMY_SUBJECT_RECORDS} />
      </section>

      <section className="two-column-grid">
        <article className="panel">
          <p className="eyebrow">Design rules</p>
          <h2>What stays true after the split</h2>
          <ul className="goal-list">
            {SIMULATION_PRINCIPLES.slice(0, 4).map((principle) => (
              <li key={principle.title}>
                <strong>{principle.title}:</strong> {principle.summary}
              </li>
            ))}
          </ul>
        </article>

        <article className="panel emphasis-card">
          <p className="eyebrow">Roadmap snapshot</p>
          <h2>Where the simulation platform goes next</h2>
          <ul className="goal-list">
            {SIMULATION_PHASES.slice(0, 3).map((phase) => (
              <li key={phase.phase}>
                <strong>{phase.phase}:</strong> {phase.deliverables}
              </li>
            ))}
          </ul>
          <p className="muted">
            {correctedCount} corrected curriculum labs remain labeled explicitly, while the new academy
            tracks provide a broader public-facing simulation surface.
          </p>
          <div className="button-row">
            <Link className="primary-button" href="/modules/nisq-hybrid-workflows">
              Open Module 1
            </Link>
            <Link
              className="secondary-button"
              href="/simulations/subjects/quantum-mechanics-and-information"
            >
              Open subject labs
            </Link>
            <Link className="secondary-button" href="/projects">
              Review project flows
            </Link>
          </div>
        </article>
      </section>
    </div>
  );
}
