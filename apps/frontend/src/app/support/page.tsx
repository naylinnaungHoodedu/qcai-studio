import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { SupportIntakeForm } from "@/components/support-intake-form";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { SUPPORT_RESPONSE_TARGETS } from "@/lib/operations-governance";
import { CONTACT_EMAIL, OWNER_NAME, REPOSITORY_URL, SITE_URL } from "@/lib/site";

const SUPPORT_SURFACES = [
  {
    eyebrow: "General support",
    title: "Product and learner questions",
    description:
      "Use email for access issues, curriculum questions, account deletion help, and problems with lessons, quizzes, builder flows, or project work.",
  },
  {
    eyebrow: "Privacy",
    title: "Data and policy requests",
    description:
      "Use the same public contact path for privacy questions, correction requests, and help clearing local-account data that was not resolved through the account page.",
  },
  {
    eyebrow: "Partnerships",
    title: "Institutional review and pilots",
    description:
      "Prospective academic or partner conversations should include the intended audience, pilot scope, expected timeline, and whether the request is evaluative or commercial.",
  },
  {
    eyebrow: "Security",
    title: "Responsible disclosure",
    description:
      "Security concerns should be reported privately to the operator rather than posted publicly. A standardized disclosure file is published at /.well-known/security.txt.",
  },
] as const;

const SUPPORT_EXPECTATIONS = [
  "The public support model is direct maintainer response, not a staffed 24/7 help desk.",
  "The operator identity for the public deployment is disclosed on the site and tied to the public repository and attribution pages.",
  "The public domain does not currently expose self-serve checkout or instant paid enrollment.",
] as const;

export const metadata: Metadata = buildPageMetadata({
  title: "Support, Contact, and Trust",
  description:
    "Review operator identity, support channels, security disclosure, and the current public-offering status for QC+AI Studio.",
  path: "/support",
});

export default function SupportPage() {
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "ContactPage",
      name: "QC+AI Studio support",
      url: `${SITE_URL}/support`,
      email: CONTACT_EMAIL,
    },
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "Support", path: "/support" },
    ]),
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="support-jsonld" />
      <section className="hero">
        <div className="hero-copy">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Support" },
            ]}
          />
          <p className="eyebrow">Support and trust</p>
          <h1>Operator identity, support contact, and public-offering status are explicit.</h1>
          <p className="hero-text">
            QC+AI Studio is operated publicly by {OWNER_NAME}. This page exists so learners, evaluators, and partner
            reviewers can see how to request help, where to send privacy or security questions, and what the current
            commercial posture of the public site actually is.
          </p>
          <div className="button-row">
            <Link className="primary-button" href="#support-intake">
              Open support intake
            </Link>
            <Link className="secondary-button" href="/audit-fixtures">
              Review audit fixtures
            </Link>
            <Link className="secondary-button" href="/privacy">
              Review privacy
            </Link>
            <Link className="secondary-button" href="/status">
              View status
            </Link>
            <a className="secondary-button" href={REPOSITORY_URL} rel="noreferrer" target="_blank">
              Inspect GitHub
            </a>
          </div>
        </div>

        <div className="analytics-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Operator</span>
            <strong className="about-metric-value">{OWNER_NAME}</strong>
            <p>Human product ownership, publication decisions, and final review stay with the named operator.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Support channel</span>
            <strong className="about-metric-value">Structured intake</strong>
            <p>
              Public support, privacy, and partner requests can use the intake form below or{" "}
              <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
            </p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Commercial status</span>
            <strong className="about-metric-value">No public checkout</strong>
            <p>The site is not currently a paid self-serve public offering.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Security disclosure</span>
            <strong className="about-metric-value">Live</strong>
            <p>
              Responsible-disclosure details are published at{" "}
              <Link href="/.well-known/security.txt">/.well-known/security.txt</Link>.
            </p>
          </article>
        </div>
      </section>

      <section className="two-column-grid">
        {SUPPORT_SURFACES.map((surface) => (
          <article className="panel legal-copy" key={surface.title}>
            <p className="eyebrow">{surface.eyebrow}</p>
            <h2>{surface.title}</h2>
            <p>{surface.description}</p>
          </article>
        ))}
      </section>

      <section className="two-column-grid">
        {SUPPORT_RESPONSE_TARGETS.map((item) => (
          <article className="panel legal-copy" key={item.title}>
            <p className="eyebrow">{item.title}</p>
            <h2>{item.target}</h2>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>

      <section className="panel legal-copy" id="support-intake">
        <h2>Structured support intake</h2>
        <p>
          Use the form below for product help, privacy questions, partnership reviews, or responsible-disclosure
          follow-up. The public intake route records a ticket reference and keeps the request inside the first-party
          QC+AI support path.
        </p>
        <SupportIntakeForm />
      </section>

      <section className="panel legal-copy">
        <h2>Commercial and enrollment clarity</h2>
        <p>
          The public QC+AI Studio site currently operates as a public learning platform and technical evaluation
          surface. It does not expose self-serve checkout, subscription billing, or instant paid enrollment on the
          public domain.
        </p>
        <p>
          If an institutional pilot, sponsored review, or manual commercial agreement is offered, pricing, access
          scope, timelines, and cancellation or refund terms should be confirmed in writing before any payment is
          requested or accepted.
        </p>
        <h2>Support expectations</h2>
        <p>{SUPPORT_EXPECTATIONS[0]}</p>
        <p>{SUPPORT_EXPECTATIONS[1]}</p>
        <p>{SUPPORT_EXPECTATIONS[2]}</p>
        <p>
          Current response targets and public release notes are summarized on the <Link href="/status">status page</Link>.
        </p>
        <h2>Related public references</h2>
        <p>
          See the <Link href="/about">about page</Link> for curriculum scope and ownership, the{" "}
          <Link href="/attribution">attribution page</Link> for build-process transparency, the{" "}
          <Link href="/privacy">privacy policy</Link> for data handling, the <Link href="/accessibility">accessibility page</Link>{" "}
          for audit status, the <Link href="/status">status page</Link> for operations, the{" "}
          <Link href="/audit-fixtures">fictional audit-fixtures page</Link> for reusable QA personas and commands, and the{" "}
          <Link href="/terms">terms of use</Link> for platform conditions.
        </p>
      </section>
    </div>
  );
}
