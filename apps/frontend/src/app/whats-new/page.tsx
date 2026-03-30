import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import {
  COMPLETION_SIGNAL_NOTES,
  EXPANSION_ROADMAP,
  FEATURE_AVAILABILITY,
  RECENT_UPDATES,
} from "@/lib/public-status";
import { SITE_URL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "What's New and Product Roadmap",
  description:
    "Review recent public releases, feature-availability status, curriculum expansion plans, and completion-signal roadmap for QC+AI Studio.",
  path: "/whats-new",
});

export default function WhatsNewPage() {
  const structuredData = [
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "What's New", path: "/whats-new" },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: "QC+AI Studio updates and roadmap",
      url: `${SITE_URL}/whats-new`,
      description:
        "Public release notes, feature availability, and roadmap for QC+AI Studio.",
    },
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="whats-new-jsonld" />
      <section className="hero about-hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "What's New" },
            ]}
          />
          <p className="eyebrow">Release notes</p>
          <h1>Recent releases, current status, and the next visible growth steps.</h1>
          <p className="hero-text">
            QC+AI Studio now spans a broader eleven-module public curriculum, even though it is still
            not a full fifteen-week academy. This page makes the current release state, the
            feature-availability boundaries, and the growth plan public.
          </p>
          <div className="button-row">
            <Link className="primary-button" href="/modules">
              Review modules
            </Link>
            <Link className="secondary-button" href="/simulations">
              Review simulations
            </Link>
            <Link className="secondary-button" href="/projects">
              Review projects
            </Link>
          </div>
        </div>
        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Recent updates</span>
            <strong className="about-metric-value">{RECENT_UPDATES.length}</strong>
            <p>Visible release notes published directly on the public site.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Availability checks</span>
            <strong className="about-metric-value">{FEATURE_AVAILABILITY.length}</strong>
            <p>Public feature states made explicit so visitors know what is live, fallback, or gated.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Roadmap tracks</span>
            <strong className="about-metric-value">{EXPANSION_ROADMAP.length}</strong>
            <p>Curriculum, simulator, credential, and operational growth paths are now visible.</p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Recent releases</p>
          <h2>Public-facing changes</h2>
          <p>These are the most recent public improvements pushed to the live site and GitHub repository.</p>
        </div>
        <div className="module-grid">
          {RECENT_UPDATES.map((item) => (
            <article className="panel" key={`${item.date}-${item.title}`}>
              <p className="eyebrow">{item.date}</p>
              <h2>{item.title}</h2>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Feature availability</p>
          <h2>What is fully live, guest-first, or environment-gated</h2>
          <p>
            First-time visitors should not have to infer feature maturity from trial and error. The public deployment now describes that state directly.
          </p>
        </div>
        <div className="module-grid">
          {FEATURE_AVAILABILITY.map((item) => (
            <article className="panel" key={item.title}>
              <div className="panel-header">
                <div className="stack">
                  <p className="eyebrow">Status</p>
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
          <p className="eyebrow">Roadmap</p>
          <h2>Growth path for curriculum, practice, and credentials</h2>
          <p>
            The roadmap now acknowledges both content volume and learner outcomes. Expansion is not hidden behind vague ambition statements.
          </p>
        </div>
        <div className="two-column-grid">
          <article className="panel">
            <p className="eyebrow">Expansion roadmap</p>
            <h2>Visible next steps</h2>
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
            <h2>What the platform recognizes today</h2>
            <ul className="goal-list">
              {COMPLETION_SIGNAL_NOTES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className="muted">
              Community discussions, the first interactive simulator build, broader mobile testing, and external discoverability work remain active follow-up items rather than hidden promises.
            </p>
          </article>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">External operations</p>
          <h2>Tasks that require platform-owner action outside the repo</h2>
          <p>
            A few discoverability and brand-protection items are real, but they cannot be completed solely by editing this repository.
          </p>
        </div>
        <ul className="goal-list">
          <li>Submit the verified domain to Google Search Console so indexing can be requested directly.</li>
          <li>Register or acquire an exact-match `quantumlearn.academy` redirect if brand alignment and typo protection matter.</li>
          <li>Monitor search indexing, backlink growth, and Lighthouse trends as ongoing operational work rather than one-time code changes.</li>
        </ul>
      </section>
    </div>
  );
}
