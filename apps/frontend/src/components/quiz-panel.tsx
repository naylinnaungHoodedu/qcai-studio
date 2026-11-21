"use client";

import { useMemo, useState } from "react";

import { postAnalyticsEvent, recordQuizAttempt } from "@/lib/api";
import { feedbackFor } from "@/lib/quiz-feedback";
import { QuizAttemptResult, QuizQuestion } from "@/lib/types";

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

// Plan Phase 4 B (R-42): the questions carry no answer key, and the panel computes no score. The server scores a saved
// attempt and returns its feedback; the model answer and rubric of each answered question come from that response.
// The feedback arrives after a network call, so the save result is announced in a live region (WCAG 2.1 4.1.3), and
// each question's input names its feedback (aria-describedby).
export function QuizPanel({
  lessonSlug,
  questions,
}: {
  lessonSlug: string;
  questions: QuizQuestion[];
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAttempt, setSavedAttempt] = useState<QuizAttemptResult | null>(null);

  const answeredCount = useMemo(() => {
    return questions.reduce((total, question) => {
      return total + (answers[question.id]?.trim() ? 1 : 0);
    }, 0);
  }, [answers, questions]);
  const hasFreeResponseQuestion = questions.some((question) => question.choices.length === 0);

  async function handleSaveAttempt() {
    if (!answeredCount) {
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      const result = await recordQuizAttempt(lessonSlug, answers);
      setSavedAttempt(result);
      void postAnalyticsEvent("quiz_attempt_saved", lessonSlug, {
        answered_count: answeredCount,
        question_count: questions.length,
        score: result.score,
      }).catch(() => null);
    } catch (error) {
      setSaveError(toErrorMessage(error, "Could not save this attempt."));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Quiz</p>
          <h2>Exam-style check</h2>
        </div>
      </div>
      <div className="stack">
        {questions.map((question, index) => {
          const feedback = feedbackFor(question.id, savedAttempt);
          const feedbackId = `quiz-feedback-${question.id}`;
          const describedBy = feedback.state === "none" ? undefined : feedbackId;
          return (
            <article className="quiz-card" key={question.id}>
              <p className="quiz-index">
                Question {index + 1} · {question.difficulty}
              </p>
              <h3>{question.prompt}</h3>
              {question.choices.length ? (
                <div className="choice-list">
                  {question.choices.map((choice) => (
                    <label className="choice-item" key={choice}>
                      <input
                        aria-describedby={describedBy}
                        checked={answers[question.id] === choice}
                        name={question.id}
                        onChange={() =>
                          setAnswers((current) => ({
                            ...current,
                            [question.id]: choice,
                          }))
                        }
                        type="radio"
                      />
                      <span>{choice}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <textarea
                  aria-describedby={describedBy}
                  aria-label={`Answer for question ${index + 1}: ${question.prompt}`}
                  className="note-input"
                  onChange={(event) =>
                    setAnswers((current) => ({
                      ...current,
                      [question.id]: event.target.value,
                    }))
                  }
                  placeholder="Write your answer"
                  rows={4}
                  value={answers[question.id] ?? ""}
                />
              )}
              {feedback.state === "correct" || feedback.state === "incorrect" ? (
                <div className="quiz-result" id={feedbackId}>
                  <p>
                    <strong>{feedback.state === "correct" ? "Correct" : "Not correct"}</strong>
                  </p>
                  <p>
                    <strong>Model answer:</strong> {feedback.answer}
                  </p>
                  {feedback.explanation ? <p className="muted">{feedback.explanation}</p> : null}
                </div>
              ) : null}
              {feedback.state === "unanswered" ? (
                <p className="muted" id={feedbackId}>
                  Answer this question and save an attempt to see its rubric.
                </p>
              ) : null}
            </article>
          );
        })}
      </div>
      <div className="button-row">
        <button
          className="primary-button"
          disabled={isSaving || answeredCount === 0}
          onClick={() => void handleSaveAttempt()}
          type="button"
        >
          {isSaving ? "Saving..." : "Save attempt"}
        </button>
        <div className="score-pill">Answered: {answeredCount} / {questions.length}</div>
      </div>
      {hasFreeResponseQuestion ? (
        <p className="muted">
          Short answers are scored on the server by exact match; use the model answer shown after saving for final judgment.
        </p>
      ) : null}
      <div aria-live="polite" role="status">
        {saveError ? <p className="muted">{saveError}</p> : null}
        {savedAttempt ? (
          <p className="muted">
            Saved attempt #{savedAttempt.attempt_id}. Recorded score: {savedAttempt.score} / {questions.length}.
            {savedAttempt.feedback?.length ? " Feedback is shown under each question." : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}
