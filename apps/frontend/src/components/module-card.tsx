import Link from "next/link";

import { ModuleProgress, ModuleSummary } from "@/lib/types";

function formatStatus(status: string): string {
  if (status === "in_progress") {
    return "In progress";
  }
  if (status === "completed") {
    return "Completed";
  }
  return "Not started";
}

export function ModuleCard({
  module,
  progress,
}: {
  module: ModuleSummary;
  progress?: ModuleProgress;
}) {
  return (
    <article className="module-card">
      <div className="module-card-header">
        <p className="eyebrow">Module</p>
        {progress ? <span className={`status-pill ${progress.status}`}>{formatStatus(progress.status)}</span> : null}
      </div>
      <h3>{module.title}</h3>
      <p>{module.summary}</p>
      <ul className="goal-list">
        {module.learning_goals.slice(0, 3).map((goal) => (
          <li key={goal}>{goal}</li>
        ))}
      </ul>
      {progress ? (
        <div className="module-progress">
          <div className="module-progress-track" aria-hidden="true">
            <span style={{ width: `${progress.progress_percent}%` }} />
          </div>
          <p className="muted">
            {progress.completed_lessons} / {progress.total_lessons} lessons completed
            {progress.average_score_percent != null ? ` · avg quiz ${progress.average_score_percent}%` : ""}
          </p>
        </div>
      ) : null}
      <div className="module-card-footer">
        <span>
          {module.lesson_slugs.length} {module.lesson_slugs.length === 1 ? "lesson" : "lessons"}
        </span>
        <Link href={`/modules/${module.slug}`}>Open module</Link>
      </div>
    </article>
  );
}
