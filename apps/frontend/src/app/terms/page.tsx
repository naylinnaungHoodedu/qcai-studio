import type { Metadata } from "next";

import { buildPageMetadata } from "@/lib/metadata";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "Terms of Use",
  description:
    "Review the educational-use terms, acceptable-use expectations, and platform limitations for QC+AI Studio.",
  path: "/terms",
});

export default function TermsPage() {
  return (
    <div className="page-stack">
      <section className="section-block">
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
