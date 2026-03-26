import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchModule } from "@/lib/api";

type ModulePageProps = {
  params: Promise<{ slug: string }>;
};

export default async function ModulePage({ params }: ModulePageProps) {
  const { slug } = await params;
  const data = await fetchModule(slug).catch(() => null);

  if (!data) {
    notFound();
  }

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Module</p>
        <h1>{data.module.title}</h1>
        <p className="hero-text">{data.module.summary}</p>
        <div className="two-column-grid">
          <div className="panel">
            <h2>Learning goals</h2>
            <ul className="goal-list">
              {data.module.learning_goals.map((goal) => (
                <li key={goal}>{goal}</li>
              ))}
            </ul>
          </div>
          <div className="panel">
            <h2>Source highlights</h2>
            <ul className="goal-list">
              {data.module.source_highlights.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Lessons</p>
          <h2>Module lessons and study paths</h2>
        </div>
        <div className="lesson-list">
          {data.lessons.map((lesson) => (
            <article key={lesson.slug} className="lesson-card">
              <div>
                <h3>{lesson.title}</h3>
                <p>{lesson.summary}</p>
                <ul className="goal-list">
                  {lesson.key_ideas.map((idea) => (
                    <li key={idea}>{idea}</li>
                  ))}
                </ul>
              </div>
              <div className="lesson-actions">
                <Link className="primary-button" href={`/lessons/${lesson.slug}`}>
                  Open lesson
                </Link>
                <Link className="secondary-button" href={`/flashcards/${lesson.slug}`}>
                  Flashcards
                </Link>
                <Link className="secondary-button" href={`/quiz/${lesson.slug}`}>
                  Quiz
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
