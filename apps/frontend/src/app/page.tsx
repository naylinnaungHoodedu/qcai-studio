import Link from "next/link";

import { ModuleCard } from "@/components/module-card";
import { fetchCourseOverview, fetchCourseProgress } from "@/lib/api";

const REFERENCES = [
  "P. Raj, B. Sundaravadivazhagan, M. Ouaissa, V. Kavitha, and K. Shantha Kumari, Eds., Quantum Computing and Artificial Intelligence: The Industry Use Cases. Hoboken, NJ, USA: John Wiley & Sons / Scrivener Publishing LLC, 2025, ISBN: 978-1-394-24236-8.",
  "S. Ali, F. Chicano, and A. Moraglio, Eds., Quantum Computing and Artificial Intelligence: First International Workshop, QC+AI 2025, Philadelphia, PA, USA, March 3, 2025, Proceedings, ser. Communications in Computer and Information Science, vol. 2813. Cham, Switzerland: Springer Nature Switzerland AG, 2026, ISSN: 1865-0929 (print), 1865-0937 (electronic), ISBN: 978-3-032-15930-4 (print), 978-3-032-15931-1 (eBook). doi: 10.1007/978-3-032-15931-1.",
  "S. Ali, F. Chicano, and A. Moraglio, Eds., Quantum Computing and Artificial Intelligence: Second International Workshop, QC+AI 2026, Singapore, January 27, 2026, Proceedings, ser. Communications in Computer and Information Science, vol. 2872. Cham, Switzerland: Springer Nature Switzerland AG, 2026, ISSN: 1865-0929 (print), 1865-0937 (electronic), ISBN: 978-3-032-17624-0 (print), 978-3-032-17625-7 (eBook). doi: 10.1007/978-3-032-17625-7.",
];

export default async function HomePage() {
  const [course, progress] = await Promise.all([fetchCourseOverview(), fetchCourseProgress()]);
  const moduleProgressBySlug = new Map(progress.modules.map((item) => [item.module_slug, item]));

  return (
    <div className="page-stack">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Quantum Hardware Perspective</p>
          <h1>Learn QC+AI through the realities of superconducting hardware and hybrid system design.</h1>
          <p className="hero-text">
            This course is built from the local QC+AI research and industry-use-case materials. It treats routing, noise, qubit scarcity,
            optimization reformulation, hybrid orchestration, application-specific evidence, and commercialization context as first-class teaching objects.
          </p>
          <div className="button-row">
            <Link className="primary-button" href={`/modules/${course.modules[0]?.slug}`}>
              Start with the course path
            </Link>
            <Link className="secondary-button" href="/search">
              Search materials
            </Link>
          </div>
        </div>
        <div className="hero-grid">
          <div className="hero-panel">
            <p className="eyebrow">Progress</p>
            <h2>{progress.progress_percent}% study momentum</h2>
            <p className="muted">
              {progress.completed_lessons} completed lessons, {progress.visited_lessons} visited lessons, {course.modules.length} modules in
              the study path
            </p>
          </div>
          <div className="hero-panel">
            <h2>References</h2>
            <ol className="reference-list">
              {REFERENCES.map((reference, index) => (
                <li key={reference} className="reference-item">
                  <span className="eyebrow">Reference {index + 1}</span>
                  <p>{reference}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Course Architecture</p>
          <h2>{course.title}</h2>
          <p>{course.summary}</p>
        </div>
        <div className="module-grid">
          {course.modules.map((module) => (
            <ModuleCard key={module.slug} module={module} progress={moduleProgressBySlug.get(module.slug)} />
          ))}
        </div>
      </section>
    </div>
  );
}
