import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { NotesPanel } from "@/components/notes-panel";
import { QAPanel } from "@/components/qa-panel";
import { StructuredData } from "@/components/structured-data";
import { VideoPanel } from "@/components/video-panel";
import { fetchCourseOverview, fetchLesson, getClientApiBaseUrl } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { SITE_URL } from "@/lib/site";

type LessonPageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: LessonPageProps): Promise<Metadata> {
  const { slug } = await params;
  const lesson = await fetchLesson(slug).catch(() => null);

  if (!lesson) {
    return buildPageMetadata({
      title: "Lesson unavailable",
      description: "The requested QC+AI lesson could not be loaded.",
      path: `/lessons/${slug}`,
      index: false,
    });
  }

  return buildPageMetadata({
    title: lesson.title,
    description: lesson.summary,
    path: `/lessons/${lesson.slug}`,
    type: "article",
  });
}

export default async function LessonPage({ params }: LessonPageProps) {
  const { slug } = await params;
  const [lesson, course] = await Promise.all([
    fetchLesson(slug).catch(() => null),
    fetchCourseOverview().catch(() => null),
  ]);

  if (!lesson) {
    notFound();
  }

  const assetBaseUrl = getClientApiBaseUrl();
  const moduleSummary = course?.modules.find((item) => item.slug === lesson.module_slug) ?? null;
  const orderedLessons = course?.modules.flatMap((module) => module.lesson_slugs) ?? [];
  const currentLessonIndex = orderedLessons.indexOf(lesson.slug);
  const previousLessonSlug = currentLessonIndex > 0 ? orderedLessons[currentLessonIndex - 1] : null;
  const nextLessonSlug =
    currentLessonIndex >= 0 && currentLessonIndex < orderedLessons.length - 1
      ? orderedLessons[currentLessonIndex + 1]
      : null;
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
        { "@type": "ListItem", position: 2, name: "Modules", item: `${SITE_URL}/modules` },
        ...(moduleSummary
          ? [
              {
                "@type": "ListItem",
                position: 3,
                name: moduleSummary.title,
                item: `${SITE_URL}/modules/${lesson.module_slug}`,
              },
            ]
          : []),
        {
          "@type": "ListItem",
          position: moduleSummary ? 4 : 3,
          name: lesson.title,
          item: `${SITE_URL}/lessons/${lesson.slug}`,
        },
      ],
    },
    {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: lesson.title,
      description: lesson.summary,
      url: `${SITE_URL}/lessons/${lesson.slug}`,
    },
  ];

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id={`lesson-${lesson.slug}-jsonld`} />
      <section className="section-block">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Modules", href: "/modules" },
            ...(moduleSummary ? [{ label: moduleSummary.title, href: `/modules/${lesson.module_slug}` }] : []),
            { label: lesson.title },
          ]}
        />
        <p className="eyebrow">Lesson</p>
        <h1>{lesson.title}</h1>
        <p className="hero-text">{lesson.summary}</p>
        <div className="button-row">
          {moduleSummary ? (
            <Link className="secondary-button" href={`/modules/${lesson.module_slug}`}>
              Back to module
            </Link>
          ) : null}
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

      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Continue learning</p>
          <h2>Move through the course path</h2>
          <p>
            Lessons are ordered intentionally. Use the navigation below to return to the parent module or continue to the next lesson without breaking study flow.
          </p>
        </div>
        <div className="lesson-list">
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Previous</p>
              <h3>{previousLessonSlug ? "Return to the previous lesson" : "You are at the start of the sequence"}</h3>
              <p>
                {previousLessonSlug
                  ? "Revisit the earlier lesson if you want to reinforce the prerequisite idea before moving on."
                  : "There is no earlier lesson in the current public ordering."}
              </p>
            </div>
            <div className="lesson-actions">
              {previousLessonSlug ? (
                <Link className="secondary-button" href={`/lessons/${previousLessonSlug}`}>
                  Previous lesson
                </Link>
              ) : (
                <Link className="secondary-button" href="/modules">
                  Open modules
                </Link>
              )}
            </div>
          </article>
          <article className="lesson-card">
            <div>
              <p className="eyebrow">Next</p>
              <h3>{nextLessonSlug ? "Advance to the next lesson" : "You reached the end of the current sequence"}</h3>
              <p>
                {nextLessonSlug
                  ? "Continue directly into the next lesson in the course ordering."
                  : "Return to the curriculum hub or projects to choose the next study surface."}
              </p>
            </div>
            <div className="lesson-actions">
              {nextLessonSlug ? (
                <Link className="primary-button" href={`/lessons/${nextLessonSlug}`}>
                  Next lesson
                </Link>
              ) : (
                <Link className="primary-button" href="/projects">
                  Open projects
                </Link>
              )}
            </div>
          </article>
        </div>
      </section>
    </div>
  );
}
