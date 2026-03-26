"use client";

import { useMemo, useState } from "react";

import { postAnalyticsEvent, recordQuizAttempt } from "@/lib/api";
import { QuizQuestion } from "@/lib/types";

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function QuizPanel({
  lessonSlug,
  questions,
}: {
  lessonSlug: string;
  questions: QuizQuestion[];
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [showResults, setShowResults] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAttemptId, setSavedAttemptId] = useState<number | null>(null);

  const score = useMemo(() => {
    return questions.reduce((total, question) => {
      return total + (answers[question.id] === question.answer ? 1 : 0);
    }, 0);
  }, [answers, questions]);
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
      const result = await recordQuizAttempt(lessonSlug, score, answers);
      setSavedAttemptId(result.attempt_id);
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
        {questions.map((question, index) => (
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
            {showResults ? (
              <div className="quiz-result">
                <p>
                  <strong>Model answer:</strong> {question.answer}
                </p>
                <p className="muted">{question.explanation}</p>
              </div>
            ) : null}
          </article>
        ))}
      </div>
      <div className="button-row">
        <button className="secondary-button" onClick={() => setShowResults((state) => !state)} type="button">
          {showResults ? "Hide rubric" : "Reveal rubric"}
        </button>
        <button
          className="primary-button"
          disabled={isSaving || answeredCount === 0}
          onClick={() => void handleSaveAttempt()}
          type="button"
        >
          {isSaving ? "Saving..." : "Save attempt"}
        </button>
        <div className="score-pill">
          Auto-score: {score} / {questions.length}
        </div>
        <div className="score-pill">Answered: {answeredCount} / {questions.length}</div>
      </div>
      {hasFreeResponseQuestion ? (
        <p className="muted">Short-answer items use an auto-score preview for study flow. Use the rubric for final judgment.</p>
      ) : null}
      {saveError ? <p className="muted">{saveError}</p> : null}
      {savedAttemptId ? <p className="muted">Saved attempt #{savedAttemptId}.</p> : null}
    </section>
  );
}
