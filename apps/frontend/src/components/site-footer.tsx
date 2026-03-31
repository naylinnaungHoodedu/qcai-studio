import Link from "next/link";

import {
  ATTRIBUTION_STATEMENT,
  CONTACT_EMAIL,
  OWNER_NAME,
  REPOSITORY_URL,
} from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-grid">
        <section className="footer-panel">
          <p className="eyebrow">Contact</p>
          <h2>{OWNER_NAME}</h2>
          <p>{ATTRIBUTION_STATEMENT}</p>
          <a className="footer-link" href={`mailto:${CONTACT_EMAIL}`}>
            {CONTACT_EMAIL}
          </a>
        </section>

        <section className="footer-panel">
          <p className="eyebrow">Policies</p>
          <nav className="footer-link-list" aria-label="Footer links">
            <Link href="/privacy">Privacy policy</Link>
            <Link href="/terms">Terms of use</Link>
            <Link href="/support">Support and trust</Link>
            <Link href="/status">Status and operations</Link>
            <Link href="/accessibility">Accessibility</Link>
            <Link href="/attribution">Attribution</Link>
            <Link href="/account">Account and sign-in</Link>
          </nav>
        </section>

        <section className="footer-panel">
          <p className="eyebrow">Project</p>
          <p>
            Review the repository, implementation context, and submission framing behind the public QC+AI learning platform.
          </p>
          <nav className="footer-link-list" aria-label="Project links">
            <Link href="/modules">Modules and prerequisites</Link>
            <Link href="/simulations">Simulation program</Link>
            <Link href="/whats-new">What&apos;s new</Link>
            <Link href="/about">About QC+AI Studio</Link>
            <a className="footer-link" href={REPOSITORY_URL} rel="noreferrer" target="_blank">
              GitHub repository
            </a>
          </nav>
        </section>
      </div>
    </footer>
  );
}
