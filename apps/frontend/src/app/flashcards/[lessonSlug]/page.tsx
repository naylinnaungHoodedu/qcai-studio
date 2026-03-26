import { notFound } from "next/navigation";

import { FlashcardDeck } from "@/components/flashcard-deck";
import { fetchLesson } from "@/lib/api";

type FlashcardsPageProps = {
  params: Promise<{ lessonSlug: string }>;
};

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
