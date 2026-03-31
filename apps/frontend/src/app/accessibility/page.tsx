import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import {
  ACCESSIBILITY_FIX_LOG,
  ACCESSIBILITY_TRACKED_FOLLOWUPS,
  ACCESSIBILITY_VALIDATION_LOG,
} from "@/lib/operations-governance";

export const metadata: Metadata = buildPageMetadata({
  title: "Accessibility Validation",
  description:
    "Review the public keyboard, automation, and tracked assistive-technology validation notes for QC+AI Studio.",
  path: "/accessibility",
});

export default function AccessibilityPage() {
  const structuredData = buildBreadcrumbStructuredData([
    { name: "Home", path: "/" },
    { name: "Accessibility", path: "/accessibility" },
  ]);

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="accessibility-breadcrumb-jsonld" />
      <section className="section-block">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Accessibility" },
          ]}
        />
        <p className="eyebrow">Accessibility</p>
        <h1>Accessibility validation is tracked publicly instead of hidden behind release notes.</h1>
        <p className="hero-text">
          This page summarizes the current WCAG-oriented validation work on QC+AI Studio: keyboard checks, browser
          automation, live fixes, and the assistive-technology follow-ups that still require a dedicated lab
          environment.
        </p>
      </section>

      <section className="two-column-grid">
        {ACCESSIBILITY_VALIDATION_LOG.map((item) => (
          <article className="panel legal-copy" key={item.flow}>
            <p className="eyebrow">{item.status}</p>
            <h2>{item.flow}</h2>
            <p>{item.detail}</p>
          </article>
        ))}
      </section>

      <section className="panel legal-copy">
        <h2>Fixes already in the live public deployment</h2>
        <div className="stack">
          {ACCESSIBILITY_FIX_LOG.map((item) => (
            <article className="metric-card" key={item.title}>
              <span className="eyebrow">Live fix</span>
              <strong className="about-metric-value">{item.title}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel legal-copy">
        <h2>Tracked follow-up work</h2>
        <ul className="compact-list">
          {ACCESSIBILITY_TRACKED_FOLLOWUPS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p>
          If you encounter an accessibility problem on a public route, use the <Link href="/support">support page</Link>{" "}
          so the issue lands in the first-party review queue instead of disappearing into generic feedback.
        </p>
      </section>
    </div>
  );
}
