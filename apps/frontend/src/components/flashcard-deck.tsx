"use client";

import { useState } from "react";

import { Flashcard } from "@/lib/types";

export function FlashcardDeck({ cards }: { cards: Flashcard[] }) {
  const [index, setIndex] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);

  if (cards.length === 0) {
    return <p>No flashcards available for this lesson.</p>;
  }

  const card = cards[index];

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Flashcards</p>
          <h2>Spaced repetition deck</h2>
        </div>
        <span>
          {index + 1} / {cards.length}
        </span>
      </div>
      <article className="flashcard">
        <p className="flashcard-level">{card.difficulty}</p>
        <h3>{card.prompt}</h3>
        {showAnswer ? <p>{card.answer}</p> : <p className="muted">Reveal the answer to check your reasoning.</p>}
      </article>
      <div className="button-row">
        <button className="secondary-button" type="button" onClick={() => setShowAnswer((state) => !state)}>
          {showAnswer ? "Hide answer" : "Reveal answer"}
        </button>
        <button
          className="primary-button"
          type="button"
          onClick={() => {
            setIndex((current) => (current + 1) % cards.length);
            setShowAnswer(false);
          }}
        >
          Next card
        </button>
      </div>
    </section>
  );
}
