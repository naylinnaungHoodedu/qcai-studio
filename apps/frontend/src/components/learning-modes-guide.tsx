import Link from "next/link";

import { LEARNING_MODES } from "@/lib/learning-modes";

/**
 * A single explainer strip that states what each interactive surface is and
 * when to use it, so Lessons / Simulations / Arena / Builder stop competing for
 * attention as four undifferentiated "interactive" things.
 */
export function LearningModesGuide() {
  return (
    <section className="section-block" aria-labelledby="learning-modes-heading">
      <div className="section-heading">
        <p className="eyebrow">Four ways to study</p>
        <h2 id="learning-modes-heading">Learn, practice, play, build — and when to use each</h2>
        <p>
          The platform gives you four ways to engage with the same material. They are meant to be used
          in this order, but you can jump between them whenever you like.
        </p>
      </div>
      <ol className="learning-modes-grid">
        {LEARNING_MODES.map((item, index) => (
          <li className="panel learning-mode-card" key={item.mode}>
            <p className="eyebrow">
              <span className="learning-mode-step" aria-hidden="true">
                {index + 1}
              </span>
              {item.mode}
            </p>
            <h3>{item.surface}</h3>
            <p>{item.what}</p>
            <p className="muted learning-mode-when">{item.when}</p>
            <Link className="secondary-button" href={item.href}>
              {item.cta}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
