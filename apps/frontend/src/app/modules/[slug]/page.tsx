import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { StructuredData } from "@/components/structured-data";
import { fetchModule } from "@/lib/api";
import { getModuleLabel } from "@/lib/module-labels";
import { buildPageMetadata } from "@/lib/metadata";
import { INDUSTRY_METHOD_NOTE } from "@/lib/public-course";
import { SITE_URL } from "@/lib/site";

type ModulePageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: ModulePageProps): Promise<Metadata> {
  const { slug } = await params;
  const data = await fetchModule(slug).catch(() => null);

  if (!data) {
    return buildPageMetadata({
      title: "Module unavailable",
      description: "The requested QC+AI module could not be loaded.",
      path: `/modules/${slug}`,
      index: false,
    });
  }

  return buildPageMetadata({
    title: data.module.title,
    description: data.module.summary,
    path: `/modules/${data.module.slug}`,
    type: "article",
  });
}

export default async function ModulePage({ params }: ModulePageProps) {
  const { slug } = await params;
  const data = await fetchModule(slug).catch(() => null);

  if (!data) {
    notFound();
  }

  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
        { "@type": "ListItem", position: 2, name: "Modules", item: `${SITE_URL}/modules` },
        { "@type": "ListItem", position: 3, name: data.module.title, item: `${SITE_URL}/modules/${data.module.slug}` },
      ],
    },
    {
      "@context": "https://schema.org",
      "@type": "CreativeWork",
      name: data.module.title,
      description: data.module.summary,
      url: `${SITE_URL}/modules/${data.module.slug}`,
    },
  ];
  const moduleLabel = getModuleLabel(data.module.slug);

  return (
    <div className="page-stack">
      <StructuredData data={structuredData} id={`module-${data.module.slug}-jsonld`} />
      <section className="section-block">
        <Breadcrumbs
          items={[
            { label: "Home", href: "/" },
            { label: "Modules", href: "/modules" },
            { label: data.module.title },
          ]}
        />
        <div className="button-row">
          {moduleLabel ? <span className="status-pill in_progress">{moduleLabel}</span> : null}
          <span className="status-pill">{data.lessons.length} lesson path</span>
        </div>
        <p className="eyebrow">{moduleLabel ?? "Module"}</p>
        <h1>{data.module.title}</h1>
        <p className="hero-text">{data.module.summary}</p>
        <div className="button-row">
          <Link className="secondary-button" href="/modules">
            Back to curriculum hub
          </Link>
          <Link className="secondary-button" href="/syllabus">
            View syllabus
          </Link>
        </div>
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
        {data.module.slug === "industry-use-cases" ? (
          <article className="panel">
            <p className="eyebrow">Methodological note</p>
            <h2>How to read this module</h2>
            <p>{INDUSTRY_METHOD_NOTE}</p>
          </article>
        ) : null}
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
