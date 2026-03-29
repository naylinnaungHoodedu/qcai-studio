import type { Metadata } from "next";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Terms of Use",
  description:
    "Review the educational-use terms, acceptable-use expectations, and platform limitations for QC+AI Studio.",
  path: "/terms",
});

export default function TermsPage() {
  const structuredData = buildBreadcrumbStructuredData([
    { name: "Home", path: "/" },
    { name: "Terms", path: "/terms" },
  ]);

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="terms-breadcrumb-jsonld" />
      <section className="section-block">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Terms" },
          ]}
        />
        <p className="eyebrow">Terms</p>
        <h1>Terms of use</h1>
        <p className="hero-text">
          QC+AI Studio is provided as an educational QC+AI learning environment. Use of the platform means using it responsibly and without misrepresenting the underlying source material.
        </p>
      </section>
      <section className="panel legal-copy">
        <h2>Acceptable use</h2>
        <p>Do not abuse the platform, scrape protected course assets, bypass access controls, or submit malicious content into notes, projects, reviews, or builder/community features.</p>
        <h2>Educational scope</h2>
        <p>The platform is designed to support study and demonstration. It does not provide professional legal, medical, or financial advice.</p>
        <h2>Content and attribution</h2>
        <p>Course materials are presented with source-grounded references and authored scaffolding. Reuse should preserve attribution and avoid claiming unsupported exclusivity.</p>
        <h2>Contact</h2>
        <p>
          Questions about platform use can be directed to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </div>
  );
}
