import Link from "next/link";

import { CONTACT_EMAIL } from "@/lib/site";

export default function NotFound() {
  return (
    <div className="page-stack">
      <section className="section-block not-found-panel">
        <p className="eyebrow">404</p>
        <h1>This route does not exist in QC+AI Studio.</h1>
        <p className="hero-text">
          The page may have moved, the slug may be invalid, or the address may never have belonged to the course.
        </p>
        <div className="button-row">
          <Link className="primary-button" href="/">
            Return to overview
          </Link>
          <Link className="secondary-button" href="/syllabus">
            Open syllabus
          </Link>
          <Link className="secondary-button" href="/search">
            Search the corpus
          </Link>
        </div>
        <p className="muted">
          If you followed a broken link, report it at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </section>
    </div>
  );
}
