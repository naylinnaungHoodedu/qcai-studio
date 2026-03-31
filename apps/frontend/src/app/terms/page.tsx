import type { Metadata } from "next";
import Link from "next/link";

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
          QC+AI Studio is provided as an educational QC+AI learning environment. Use of the platform means using it
          responsibly, respecting access controls, and not misrepresenting the underlying source material or the
          platform&apos;s commercial status.
        </p>
      </section>
      <section className="panel legal-copy">
        <h2>Acceptable use</h2>
        <p>
          Do not abuse the platform, scrape protected course assets, bypass access controls, automate disruptive use,
          or submit malicious, unlawful, or deceptive content into notes, projects, reviews, or builder/community
          features.
        </p>
        <h2>Educational scope</h2>
        <p>
          The platform is designed to support study and demonstration. It does not provide professional legal, medical,
          or financial advice, and it should not be presented as an accredited degree, licensure, or guaranteed hiring
          credential.
        </p>
        <h2>Accounts, deletion, and moderation</h2>
        <p>
          Learners are responsible for activity under their own local account or guest session. The platform may
          suspend abusive access, rate-limit misuse, or remove harmful content. Local-account deletion is available on
          the <Link href="/account">account page</Link>; related privacy handling is described in the{" "}
          <Link href="/privacy">privacy policy</Link>.
        </p>
        <h2>Content and attribution</h2>
        <p>
          Course materials are presented with source-grounded references and authored scaffolding. Reuse should
          preserve attribution and avoid claiming unsupported exclusivity, certification, or ownership over public
          source material that remains attributable to its original authors.
        </p>
        <h2>Public offering, pricing, and refunds</h2>
        <p>
          The public QC+AI Studio deployment is not currently a paid self-serve public offering. No checkout,
          subscription billing, or instant public enrollment purchase flow is exposed on this domain. If sponsored
          pilots, institutional reviews, or manual commercial arrangements are offered, pricing, access scope,
          cancellation, and any refund terms will be documented in writing before payment is accepted.
        </p>
        <h2>Education and minors</h2>
        <p>
          The course is written for technically mature learners. It is not aimed at unsupervised children. Any use by
          minors should happen through appropriate institutional, classroom, or guardian oversight consistent with local
          policy requirements.
        </p>
        <h2>Operator identity and support</h2>
        <p>
          The public operator, support path, and partner-contact information are summarized on the{" "}
          <Link href="/support">support page</Link>. Product, privacy, and security questions can also be sent to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
        <p>
          Current response targets, status notes, and browser-governance disclosures are summarized on the{" "}
          <Link href="/status">status page</Link>. Accessibility validation notes are published on the{" "}
          <Link href="/accessibility">accessibility page</Link>.
        </p>
        <h2>Contact</h2>
        <p>
          Questions about platform use can be directed to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </div>
  );
}
