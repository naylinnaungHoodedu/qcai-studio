import { notFound } from "next/navigation";

import { QuizPanel } from "@/components/quiz-panel";
import { fetchLesson } from "@/lib/api";

type QuizPageProps = {
  params: Promise<{ lessonSlug: string }>;
};

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
        <p className="hero-text">Work through the questions before revealing the model answers and rubrics.</p>
      </section>
      <QuizPanel lessonSlug={lesson.slug} questions={lesson.quiz_questions} />
    </div>
  );
}
