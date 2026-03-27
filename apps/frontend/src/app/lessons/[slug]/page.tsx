import Link from "next/link";
import { notFound } from "next/navigation";

import { NotesPanel } from "@/components/notes-panel";
import { QAPanel } from "@/components/qa-panel";
import { VideoPanel } from "@/components/video-panel";
import { fetchLesson, getClientApiBaseUrl } from "@/lib/api";

type LessonPageProps = {
  params: Promise<{ slug: string }>;
};

export default async function LessonPage({ params }: LessonPageProps) {
  const { slug } = await params;
  const lesson = await fetchLesson(slug).catch(() => null);

  if (!lesson) {
    notFound();
  }

  const assetBaseUrl = getClientApiBaseUrl();

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Lesson</p>
        <h1>{lesson.title}</h1>
        <p className="hero-text">{lesson.summary}</p>
        <div className="button-row">
          <Link className="secondary-button" href={`/flashcards/${lesson.slug}`}>
            Review flashcards
          </Link>
          <Link className="secondary-button" href={`/quiz/${lesson.slug}`}>
            Take quiz
          </Link>
        </div>
      </section>

      <div className="lesson-layout-grid">
        <VideoPanel chapters={lesson.chapters} videoAsset={lesson.video_asset} />
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Key ideas</p>
              <h2>What this lesson teaches</h2>
            </div>
          </div>
          <ul className="goal-list">
            {lesson.key_ideas.map((idea) => (
              <li key={idea}>{idea}</li>
            ))}
          </ul>
          <h3>Key notes</h3>
          <ul className="goal-list">
            {lesson.key_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <h3>Formulas and diagrams to emphasize</h3>
          <ul className="goal-list">
            {lesson.formulas.map((formula) => (
              <li key={formula}>{formula}</li>
            ))}
          </ul>
        </section>
      </div>

      <div className="lesson-layout-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Source-grounded sections</p>
              <h2>Document sections used in this lesson</h2>
            </div>
          </div>
          <div className="stack">
            {lesson.sections.length ? (
              lesson.sections.map((section) => (
                <article className="citation-card" key={section.id}>
                  <strong>{section.heading}</strong>
                  <p className="muted">{section.source_title}</p>
                  <p>{section.summary}</p>
                  <p className="muted">{section.excerpt}</p>
                </article>
              ))
            ) : (
              <article className="citation-card">
                <strong>No matched source excerpts</strong>
                <p className="muted">
                  This lesson currently relies on authored scaffolding rather than directly matched source-document sections.
                </p>
              </article>
            )}
          </div>
        </section>
        <QAPanel lessonSlug={lesson.slug} seedQuestions={lesson.learner_questions} />
      </div>

      <div className="lesson-layout-grid">
        <NotesPanel lessonSlug={lesson.slug} />
        <div className="stack">
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Source assets</p>
                <h2>Downloads and references</h2>
              </div>
            </div>
            <ul className="source-list compact">
              {lesson.source_assets.map((asset) => (
                <li key={asset.id}>
                  <span>{asset.kind}</span>
                  <a href={`${assetBaseUrl}${asset.download_url}`}>
                    {asset.title}
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Related lessons</p>
                <h2>Cross-module reinforcement</h2>
              </div>
            </div>
            <div className="stack">
              {lesson.related_lessons.map((item) => (
                <article className="citation-card" key={item.slug}>
                  <strong>{item.title}</strong>
                  <p>{item.summary}</p>
                  <p className="muted">{item.reason}</p>
                  <Link className="secondary-button inline-action" href={`/lessons/${item.slug}`}>
                    Open related lesson
                  </Link>
                </article>
              ))}
              {lesson.related_lessons.length === 0 ? (
                <p className="muted">No adjacent lessons were identified yet for this module.</p>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
