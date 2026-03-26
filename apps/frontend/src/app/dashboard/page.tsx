import Link from "next/link";

import { fetchCourseOverview, fetchCourseProgress, fetchMe } from "@/lib/api";

export default async function DashboardPage() {
  const [course, progress, user] = await Promise.all([fetchCourseOverview(), fetchCourseProgress(), fetchMe()]);

  return (
    <div className="page-stack">
      <section className="section-block">
        <p className="eyebrow">Profile</p>
        <h1>{user.user_id}</h1>
        <p className="hero-text">
          Role: {user.role}. This local MVP runs in demo mode by default, but the API contract is aligned with Auth0-based JWT and role checks.
        </p>
        <div className="dashboard-metrics">
          <article className="metric-card">
            <span className="eyebrow">Overall progress</span>
            <strong>{progress.progress_percent}%</strong>
            <p>{progress.completed_lessons} completed lessons</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Visited lessons</span>
            <strong>
              {progress.visited_lessons} / {progress.total_lessons}
            </strong>
            <p>Engagement tracked from notes, Q&A, quizzes, and lesson events.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Recent notes</span>
            <strong>{progress.recent_notes.length}</strong>
            <p>Latest saved notes are listed below for quick review.</p>
          </article>
        </div>
      </section>
      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">Study path</p>
          <h2>Suggested module sequence</h2>
          <p>Module state now reflects your recorded lesson activity, notes, and quiz outcomes.</p>
        </div>
        <div className="lesson-list">
          {course.modules.map((module, index) => {
            const moduleProgress = progress.modules.find((item) => item.module_slug === module.slug);
            return (
            <article className="lesson-card" key={module.slug}>
              <div>
                <p className="eyebrow">Step {index + 1}</p>
                <h3>{module.title}</h3>
                <p>{module.summary}</p>
                {moduleProgress ? (
                  <p className="muted">
                    {moduleProgress.status.replace("_", " ")} · {moduleProgress.completed_lessons} / {moduleProgress.total_lessons} lessons
                    complete · {moduleProgress.progress_percent}% progress
                    {moduleProgress.average_score_percent != null ? ` · avg quiz ${moduleProgress.average_score_percent}%` : ""}
                  </p>
                ) : null}
              </div>
              <div className="lesson-actions">
                <Link className="primary-button" href={`/modules/${module.slug}`}>
                  Continue
                </Link>
              </div>
            </article>
            );
          })}
        </div>
      </section>
      <div className="two-column-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Recent notes</p>
              <h2>Captured study context</h2>
            </div>
          </div>
          <div className="stack">
            {progress.recent_notes.length ? (
              progress.recent_notes.map((note) => (
                <article className="note-card" key={note.id}>
                  <p>{note.body}</p>
                  <span className="muted">
                    {note.lesson_slug} · {new Date(note.created_at).toLocaleString()}
                  </span>
                </article>
              ))
            ) : (
              <p className="muted">No saved notes yet. Add notes inside a lesson to build a study trail.</p>
            )}
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Quiz history</p>
              <h2>Recorded attempts</h2>
            </div>
          </div>
          <div className="stack">
            {progress.recent_quiz_attempts.length ? (
              progress.recent_quiz_attempts.map((attempt) => (
                <article className="citation-card" key={attempt.id}>
                  <strong>{attempt.lesson_slug}</strong>
                  <p className="muted">
                    Score {attempt.score} · {new Date(attempt.created_at).toLocaleString()}
                  </p>
                </article>
              ))
            ) : (
              <p className="muted">No quiz attempts recorded yet. Saving an attempt will populate this history.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
