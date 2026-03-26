"use client";

import { FormEvent, useState } from "react";

import { askQuestion, postAnalyticsEvent } from "@/lib/api";
import { QAResponse } from "@/lib/types";

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function QAPanel({
  lessonSlug,
  seedQuestions,
}: {
  lessonSlug: string;
  seedQuestions: string[];
}) {
  const [question, setQuestion] = useState(seedQuestions[0] ?? "");
  const [response, setResponse] = useState<QAResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }
    setIsLoading(true);
    setError(null);
    setResponse(null);
    try {
      const answer = await askQuestion(question.trim(), lessonSlug);
      setResponse(answer);
      void postAnalyticsEvent("lesson_qa_asked", lessonSlug, {
        question_length: question.trim().length,
        citation_count: answer.citations.length,
        retrieval_mode: answer.retrieval_mode,
      }).catch(() => null);
    } catch (error) {
      setError(toErrorMessage(error, "Could not retrieve an answer right now."));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">RAG Q&A</p>
          <h2>Ask this lesson</h2>
        </div>
      </div>
      <div className="prompt-pills">
        {seedQuestions.map((item) => (
          <button key={item} className="prompt-pill" onClick={() => setQuestion(item)} type="button">
            {item}
          </button>
        ))}
      </div>
      <form className="stack" onSubmit={submit}>
        <textarea
          className="note-input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={4}
        />
        <button className="primary-button" type="submit" disabled={isLoading}>
          {isLoading ? "Retrieving..." : "Ask grounded question"}
        </button>
      </form>
      {error ? <p className="muted">{error}</p> : null}
      {response ? (
        <div className="qa-response" aria-live="polite">
          <p className="retrieval-mode">{response.retrieval_mode}</p>
          <p>{response.answer}</p>
          <div className="stack">
            {response.citations.map((citation) => (
              <article className="citation-card" key={citation.chunk_id}>
                <strong>{citation.section_title}</strong>
                <p className="muted">
                  {citation.source_title}
                  {citation.timestamp_label ? ` · ${citation.timestamp_label}` : ""}
                </p>
                <p>{citation.excerpt}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
