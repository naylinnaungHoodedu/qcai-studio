import Link from "next/link";

import { PageErrorState } from "@/components/page-state";
import { fetchCourseOverview } from "@/lib/api";
import { COURSE_REFERENCES } from "@/lib/course-references";

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

  return (
    <div className="page-stack">
      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Public syllabus</p>
          <h1>{course.title}</h1>
          <p>{course.summary}</p>
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
          <h2>References and local assets</h2>
        </div>
        <ol className="reference-list">
          {COURSE_REFERENCES.map((reference, index) => (
            <li key={reference} className="reference-item">
              <span className="eyebrow">Reference {index + 1}</span>
              <p>{reference}</p>
            </li>
          ))}
        </ol>
        <ul className="source-list compact">
          {course.source_assets.map((asset) => (
            <li key={asset.id}>
              <span>{asset.kind}</span>
              <strong>{asset.title}</strong>
              <p className="muted">{asset.filename}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
