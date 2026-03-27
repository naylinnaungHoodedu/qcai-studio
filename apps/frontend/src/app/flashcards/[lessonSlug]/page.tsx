import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FlashcardDeck } from "@/components/flashcard-deck";
import { fetchLesson } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";

type FlashcardsPageProps = {
  params: Promise<{ lessonSlug: string }>;
};

export async function generateMetadata({ params }: FlashcardsPageProps): Promise<Metadata> {
  const { lessonSlug } = await params;
  const lesson = await fetchLesson(lessonSlug).catch(() => null);
  if (!lesson) {
    return buildPageMetadata({
      title: "Flashcards unavailable",
      description: "The requested QC+AI flashcard deck could not be loaded.",
      path: `/flashcards/${lessonSlug}`,
      index: false,
    });
  }

  return buildPageMetadata({
    title: `${lesson.title} Flashcards`,
    description: `Review flashcards for ${lesson.title} across definitions, workflows, and hardware constraints.`,
    path: `/flashcards/${lesson.slug}`,
    index: false,
  });
}

export default async function FlashcardsPage({ params }: FlashcardsPageProps) {
  const { lessonSlug } = await params;
  const lesson = await fetchLesson(lessonSlug).catch(() => null);
  if (!lesson) {
    notFound();
  }

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Flashcards</p>
        <h1>{lesson.title}</h1>
        <p className="hero-text">Use these cards to rehearse definitions, architectural patterns, and application constraints.</p>
      </section>
      <FlashcardDeck cards={lesson.flashcards} />
    </div>
  );
}
