"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { askQuestion, fetchQAHistory, postAnalyticsEvent } from "@/lib/api";
import { QAHistoryItem, QAResponse } from "@/lib/types";

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
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState(seedQuestions[0] ?? "");
  const [response, setResponse] = useState<QAResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const historyQuery = useQuery({
    queryKey: ["qa-history", lessonSlug],
    queryFn: () => fetchQAHistory(lessonSlug, { limit: 5 }),
  });

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
      void queryClient.invalidateQueries({ queryKey: ["qa-history", lessonSlug] });
      void postAnalyticsEvent("lesson_qa_asked", lessonSlug, {
        question_length: question.trim().length,
        citation_count: answer.citations.length,
        retrieval_mode: answer.retrieval_mode,
      }).catch(() => null);
    } catch (nextError) {
      setError(toErrorMessage(nextError, "Could not retrieve an answer right now."));
    } finally {
      setIsLoading(false);
    }
  }

  function renderHistoryItem(item: QAHistoryItem) {
    return (
      <article className="citation-card" key={item.id}>
        <strong>{item.question}</strong>
        <p className="muted">{new Date(item.created_at).toLocaleString()}</p>
        <p>{item.answer}</p>
      </article>
    );
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
        <div className="button-row">
          <button className="primary-button" type="submit" disabled={isLoading}>
            {isLoading ? "Retrieving..." : "Ask grounded question"}
          </button>
          <button
            className="secondary-button"
            onClick={() => setShowHistory((current) => !current)}
            type="button"
          >
            {showHistory ? "Hide recent questions" : "Show recent questions"}
          </button>
        </div>
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
                  {citation.timestamp_label ? ` | ${citation.timestamp_label}` : ""}
                </p>
                <p>{citation.excerpt}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}
      {showHistory ? (
        <div className="stack">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Recent questions</p>
              <h3>Last 5 grounded answers</h3>
            </div>
          </div>
          {historyQuery.isLoading ? <p className="muted">Loading recent questions...</p> : null}
          {historyQuery.isError ? (
            <p className="muted">{toErrorMessage(historyQuery.error, "Could not load recent questions.")}</p>
          ) : null}
          {(historyQuery.data ?? []).map(renderHistoryItem)}
          {historyQuery.data?.length === 0 ? (
            <p className="muted">No saved Q&A yet for this lesson.</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
