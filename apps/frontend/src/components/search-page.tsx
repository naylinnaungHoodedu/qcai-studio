"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { postAnalyticsEvent, searchContent } from "@/lib/api";
import { SearchResult } from "@/lib/types";

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

// Starter queries so a first-time visitor is never staring at a blank box.
const EXAMPLE_QUERIES = [
  "NISQ constraints",
  "QUBO logistics",
  "quantum vision",
  "few-shot learning",
  "quantum finance",
];

export function SearchPageView() {
  const [query, setQuery] = useState("QUBO logistics");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runSearch(rawQuery: string) {
    const trimmed = rawQuery.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const nextResults = await searchContent(trimmed);
      setResults(nextResults);
      void postAnalyticsEvent("course_search_ran", undefined, {
        query: trimmed,
        result_count: nextResults.length,
      }).catch(() => null);
    } catch (error) {
      setResults([]);
      setError(toErrorMessage(error, "Could not search the corpus right now."));
    } finally {
      setLoading(false);
    }
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(query);
  }

  function applyExample(example: string) {
    setQuery(example);
    void runSearch(example);
  }

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Grounded Search</p>
        <h1>Search the local QC+AI materials</h1>
        <p className="hero-text">
          Search by concept, application area, or algorithm name. Results are grounded in indexed document sections,
          curated video chapters, and lesson-authored scaffolding where the course adds prerequisite framing.
        </p>
        <form className="stack" onSubmit={handleSearch}>
          <textarea
            aria-label="Search query"
            className="note-input"
            onChange={(event) => setQuery(event.target.value)}
            rows={3}
            value={query}
          />
          <button className="primary-button" disabled={loading} type="submit">
            {loading ? "Searching..." : "Search"}
          </button>
        </form>
        <div className="prompt-pills" role="group" aria-label="Example searches">
          <span className="eyebrow">Try an example</span>
          {EXAMPLE_QUERIES.map((example) => (
            <button
              className="prompt-pill"
              disabled={loading}
              key={example}
              onClick={() => applyExample(example)}
              type="button"
            >
              {example}
            </button>
          ))}
        </div>
        {error ? <p className="muted">{error}</p> : null}
      </section>
      <section className="section-block">
        <div className="lesson-list">
          {results.map((result) => (
            <article className="citation-card" key={result.chunk_id}>
              <strong>{result.title}</strong>
              <p className="muted">
                {result.source_title}
                {result.timestamp_label ? ` | ${result.timestamp_label}` : ""} | score {result.score}
              </p>
              <p>{result.excerpt}</p>
              {result.lesson_slug ? (
                <div className="button-row">
                  <Link className="secondary-button" href={`/lessons/${result.lesson_slug}`}>
                    Open lesson
                  </Link>
                </div>
              ) : null}
            </article>
          ))}
          {!results.length ? <p className="muted">Run a search to surface source-grounded evidence.</p> : null}
        </div>
      </section>
    </div>
  );
}
