import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { ATTRIBUTION_STATEMENT, CONTACT_EMAIL, OWNER_NAME, SITE_URL } from "@/lib/site";

const REVIEW_PRACTICES = [
  "Scope, architecture, and final acceptance decisions remained human-directed.",
  "Generated code and copy were reviewed against live behavior, tests, and deployment reality before publication.",
  "Where the live product is environment-gated, the public pages now disclose that state instead of implying unavailable capabilities.",
] as const;

const HUMAN_DECISIONS = [
  "Selecting the QC+AI problem framing and the curated corpus.",
  "Deciding which claims were strong enough for the public site.",
  "Rejecting wording that overstated maturity, deployment readiness, or source certainty.",
] as const;

export const metadata: Metadata = buildPageMetadata({
  title: "Attribution and Build Process",
  description:
    "Review project ownership, AI-assistance attribution, human review practices, and the publication standards behind QC+AI Studio.",
  path: "/attribution",
});

export default function AttributionPage() {
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "CreativeWork",
      name: "QC+AI Studio attribution",
      author: OWNER_NAME,
      url: `${SITE_URL}/attribution`,
      description:
        "Human-directed, AI-assisted authorship and review disclosure for the QC+AI Studio platform.",
    },
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "Attribution", path: "/attribution" },
    ]),
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="attribution-jsonld" />
      <section className="section-block">
        <div className="section-heading">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Attribution" },
            ]}
          />
          <p className="eyebrow">Attribution</p>
          <h1>Human-directed, AI-assisted product authorship</h1>
          <p className="hero-text">{ATTRIBUTION_STATEMENT}</p>
        </div>
      </section>

      <section className="two-column-grid">
        <article className="panel legal-copy">
          <h2>Ownership</h2>
          <p>{OWNER_NAME} retains product ownership, domain direction, acceptance decisions, and final submission responsibility for QC+AI Studio.</p>
          <h2>Recommended public statement</h2>
          <p>
            QC+AI Studio is a full-stack QC+AI learning platform built and significantly enhanced using OpenAI Codex, with product ownership, domain direction, and final review led by {OWNER_NAME} ({CONTACT_EMAIL}).
          </p>
          <h2>Contact</h2>
          <p>
            Attribution questions can be directed to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
          </p>
        </article>

        <article className="panel">
          <p className="eyebrow">Human responsibilities</p>
          <h2>What remained human-led</h2>
          <ul className="goal-list">
            {HUMAN_DECISIONS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Review bar</p>
          <h2>How AI-assisted output was evaluated</h2>
          <p>
            Attribution is not just about naming the tool. It is about explaining the review process that stands between generated output and a public claim.
          </p>
        </div>
        <div className="module-grid">
          {REVIEW_PRACTICES.map((item) => (
            <article className="panel" key={item}>
              <div className="stack">
                <p className="eyebrow">Practice</p>
                <h2>{item}</h2>
              </div>
            </article>
          ))}
        </div>
        <div className="button-row">
          <Link className="secondary-button" href="/about">
            About the platform
          </Link>
          <Link className="secondary-button" href="/modules">
            Modules and prerequisites
          </Link>
        </div>
      </section>
    </div>
  );
}
