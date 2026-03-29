import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { PageErrorState } from "@/components/page-state";
import { StructuredData } from "@/components/structured-data";
import { fetchCourseOverview } from "@/lib/api";
import { COURSE_REFERENCES } from "@/lib/course-references";
import { buildPageMetadata } from "@/lib/metadata";
import { splitSyllabusAssets } from "@/lib/syllabus";
import { SITE_URL } from "@/lib/site";

export const metadata: Metadata = buildPageMetadata({
  title: "QC+AI Curriculum and Syllabus",
  description:
    "Browse the public QC+AI syllabus, module sequence, learning goals, and source references for the hardware-constrained course.",
  path: "/syllabus",
});

export default async function SyllabusPage() {
  const course = await fetchCourseOverview().catch(() => null);
  if (!course) {
    return (
      <PageErrorState
        title="The syllabus could not be loaded"
        detail="Public course structure data was unavailable for this request."
      />
    );
  }
  const { documentAssets, supplementalAssets } = splitSyllabusAssets(course.source_assets);
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "Course",
      name: course.title,
      description: course.summary,
      url: `${SITE_URL}/syllabus`,
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
        { "@type": "ListItem", position: 2, name: "Syllabus", item: `${SITE_URL}/syllabus` },
      ],
    },
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id="syllabus-jsonld" />
      <section className="section-block">
        <div className="section-heading">
          <Breadcrumbs
            items={[
              { label: "Home", href: "/" },
              { label: "Syllabus" },
            ]}
          />
          <p className="eyebrow">Public syllabus</p>
          <h1>{course.title}</h1>
          <p>{course.summary}</p>
          <div className="button-row">
            <Link className="secondary-button" href="/modules">
              Open modules hub
            </Link>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Modules</p>
          <h2>Course structure</h2>
        </div>
        <div className="lesson-list">
          {course.modules.map((module, index) => (
            <article className="lesson-card" key={module.slug}>
              <div>
                <p className="eyebrow">Module {index + 1}</p>
                <h3>{module.title}</h3>
                <p>{module.summary}</p>
                <ul className="goal-list">
                  {module.learning_goals.map((goal) => (
                    <li key={goal}>{goal}</li>
                  ))}
                </ul>
                <p className="muted">Source highlights: {module.source_highlights.join(" | ")}</p>
              </div>
              <div className="lesson-actions">
                <Link className="primary-button" href={`/modules/${module.slug}`}>
                  Open module
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Sources</p>
          <h2>References and course media</h2>
          <p>
            The numbered bibliography below represents the curated document corpus. The supplemental asset list focuses on
            non-document media so the same references are not rendered twice.
          </p>
        </div>
        <ol className="reference-list">
          {COURSE_REFERENCES.map((reference, index) => (
            <li key={reference} className="reference-item">
              <span className="eyebrow">Reference {index + 1}</span>
              <p>{reference}</p>
            </li>
          ))}
        </ol>
        {documentAssets.length ? (
          <p className="muted">
            {documentAssets.length} curated document asset{documentAssets.length === 1 ? "" : "s"} are already represented in citation form above.
          </p>
        ) : null}
        {supplementalAssets.length ? (
          <ul className="source-list compact">
            {supplementalAssets.map((asset) => (
              <li key={asset.id}>
                <span>{asset.kind}</span>
                <strong>{asset.title}</strong>
                <p className="muted">{asset.filename}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No supplemental non-document assets were published for this syllabus snapshot.</p>
        )}
      </section>
    </div>
  );
}
