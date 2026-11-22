import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { QuizPanel } from "@/components/quiz-panel";
import { fetchLesson } from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { publicQuestions } from "@/lib/quiz-feedback";

type QuizPageProps = {
  params: Promise<{ lessonSlug: string }>;
};

export async function generateMetadata({ params }: QuizPageProps): Promise<Metadata> {
  const { lessonSlug } = await params;
  const lesson = await fetchLesson(lessonSlug).catch(() => null);
  if (!lesson) {
    return buildPageMetadata({
      title: "Quiz unavailable",
      description: "The requested QC+AI quiz could not be loaded.",
      path: `/quiz/${lessonSlug}`,
      index: false,
    });
  }

  return buildPageMetadata({
    title: `${lesson.title} Quiz`,
    description: `Test your understanding of ${lesson.title} with exam-style QC+AI questions and rubric guidance.`,
    path: `/quiz/${lesson.slug}`,
  });
}

export default async function QuizPage({ params }: QuizPageProps) {
  const { lessonSlug } = await params;
  const lesson = await fetchLesson(lessonSlug).catch(() => null);
  if (!lesson) {
    notFound();
  }

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Quiz</p>
        <h1>{lesson.title}</h1>
        <p className="hero-text">Work through the questions, then save an attempt to see the model answers and rubrics.</p>
      </section>
      {/* Only the public fields reach the client component, so no answer key is serialised into the page (R-42). */}
      <QuizPanel lessonSlug={lesson.slug} questions={publicQuestions(lesson.quiz_questions)} />
    </div>
  );
}
