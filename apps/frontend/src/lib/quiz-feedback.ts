import type { QuizAttemptResult, QuizQuestion } from "@/lib/types";

// Plan Phase 4 B "keyed answers outside public payloads" (R-42): no answer key reaches a page or a client component.
// publicQuestions keeps exactly the public fields, so even a lesson payload from an older (or cached) API that still
// carries `answer` and `explanation` is stripped before the quiz page serialises it into its HTML.
export function publicQuestions(questions: ReadonlyArray<QuizQuestion & Record<string, unknown>>): QuizQuestion[] {
  return questions.map(({ id, question_type, prompt, choices, difficulty }) => ({
    id,
    question_type,
    prompt,
    choices: Array.isArray(choices) ? [...choices] : [],
    difficulty,
  }));
}

export type QuestionFeedback = {
  state: "none" | "unanswered" | "correct" | "incorrect";
  answer?: string;
  explanation?: string;
};

// The rubric of one question after a saved attempt: from the API's feedback only (the server scored it). Before an
// attempt is saved, or from an API that sends no feedback, there is nothing to show.
export function feedbackFor(questionId: string, result: QuizAttemptResult | null): QuestionFeedback {
  const item = result?.feedback?.find((entry) => entry.question_id === questionId);
  if (!item) {
    return { state: "none" };
  }
  if (!item.answered) {
    return { state: "unanswered" };
  }
  return {
    state: item.correct ? "correct" : "incorrect",
    answer: item.answer ?? undefined,
    explanation: item.explanation ?? undefined,
  };
}
