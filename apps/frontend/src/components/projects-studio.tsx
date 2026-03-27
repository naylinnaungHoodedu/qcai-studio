"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent, startTransition, useDeferredValue, useEffect, useState } from "react";

import {
  createProjectSubmission,
  fetchMyProjectSubmissions,
  fetchProjectCatalog,
  fetchProjectReviewQueue,
  requestRealtimeFeedback,
  submitPeerReview,
} from "@/lib/api";
import { ProjectBrief, ProjectSubmission, RealtimeFeedback, ReviewQueueItem } from "@/lib/types";


type ProjectsStudioProps = {
  initialCatalog: ProjectBrief[];
  initialSubmissions: ProjectSubmission[];
  initialQueue: ReviewQueueItem[];
};

type ReviewDraft = {
  feedback: string;
  rubric_scores: Record<string, number>;
};

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function buildInitialReviewDraft(item: ReviewQueueItem): ReviewDraft {
  return {
    feedback: "",
    rubric_scores: Object.fromEntries(item.rubric.map((criterion) => [criterion.id, 3])),
  };
}

export function ProjectsStudio({ initialCatalog, initialSubmissions, initialQueue }: ProjectsStudioProps) {
  const queryClient = useQueryClient();
  const [selectedProjectSlug, setSelectedProjectSlug] = useState(initialCatalog[0]?.slug ?? "");
  const [submission, setSubmission] = useState({
    title: initialCatalog[0] ? `${initialCatalog[0].title} submission` : "",
    solution_summary: "",
    implementation_notes: "",
    confidence_level: 3,
  });
  const [liveFeedback, setLiveFeedback] = useState<RealtimeFeedback | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [reviewForms, setReviewForms] = useState<Record<number, ReviewDraft>>({});

  const catalogQuery = useQuery({
    queryKey: ["project-catalog"],
    queryFn: fetchProjectCatalog,
    initialData: initialCatalog,
  });
  const submissionsQuery = useQuery({
    queryKey: ["project-submissions"],
    queryFn: fetchMyProjectSubmissions,
    initialData: initialSubmissions,
  });
  const queueQuery = useQuery({
    queryKey: ["project-review-queue"],
    queryFn: fetchProjectReviewQueue,
    initialData: initialQueue,
  });

  const selectedProject = (catalogQuery.data ?? []).find((project) => project.slug === selectedProjectSlug) ?? catalogQuery.data?.[0];
  const deferredDraft = useDeferredValue(`${submission.solution_summary}\n${submission.implementation_notes}`);

  const liveFeedbackMutation = useMutation({
    mutationFn: () =>
      requestRealtimeFeedback({
        context_type: "project_submission",
        content: `${selectedProject?.title ?? "Project"}\n${deferredDraft}`.trim(),
        project_slug: selectedProject?.slug,
      }),
    onSuccess: (result) => {
      setLiveFeedback(result);
    },
  });

  const submitMutation = useMutation({
    mutationFn: () =>
      createProjectSubmission({
        project_slug: selectedProjectSlug,
        title: submission.title,
        solution_summary: submission.solution_summary,
        implementation_notes: submission.implementation_notes,
        confidence_level: submission.confidence_level,
      }),
    onSuccess: () => {
      setSubmissionError(null);
      setSubmission({
        title: selectedProject ? `${selectedProject.title} submission` : "",
        solution_summary: "",
        implementation_notes: "",
        confidence_level: 3,
      });
      void queryClient.invalidateQueries({ queryKey: ["project-catalog"] });
      void queryClient.invalidateQueries({ queryKey: ["project-submissions"] });
      void queryClient.invalidateQueries({ queryKey: ["project-review-queue"] });
    },
    onError: (error) => {
      setSubmissionError(toErrorMessage(error, "Could not submit the project."));
    },
  });

  const reviewMutation = useMutation({
    mutationFn: ({ submissionId, draft }: { submissionId: number; draft: ReviewDraft }) =>
      submitPeerReview({
        submission_id: submissionId,
        rubric_scores: draft.rubric_scores,
        feedback: draft.feedback,
      }),
    onSuccess: (_, variables) => {
      setReviewForms((current) => {
        const next = { ...current };
        delete next[variables.submissionId];
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: ["project-submissions"] });
      void queryClient.invalidateQueries({ queryKey: ["project-review-queue"] });
      void queryClient.invalidateQueries({ queryKey: ["project-catalog"] });
    },
  });

  useEffect(() => {
    if (!selectedProject || deferredDraft.trim().length < 180) {
      return;
    }
    const timer = window.setTimeout(() => {
      liveFeedbackMutation.mutate();
    }, 650);
    return () => window.clearTimeout(timer);
  }, [deferredDraft, selectedProject, liveFeedbackMutation]);

  function selectProject(project: ProjectBrief) {
    startTransition(() => {
      setSelectedProjectSlug(project.slug);
      setSubmission({
        title: `${project.title} submission`,
        solution_summary: "",
        implementation_notes: "",
        confidence_level: 3,
      });
      setLiveFeedback(null);
      setSubmissionError(null);
    });
  }

  function handleSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitMutation.mutate();
  }

  function reviewDraftFor(item: ReviewQueueItem): ReviewDraft {
    return reviewForms[item.submission_id] ?? buildInitialReviewDraft(item);
  }

  return (
    <div className="page-stack">
      <section className="section-block project-hero">
        <div className="section-heading">
          <p className="eyebrow">Applied learning</p>
          <h1>Hands-on projects and peer-reviewed assignments</h1>
          <p>
            Move beyond passive watching. Build design artifacts, get live AI feedback while drafting, and review peer
            submissions against explicit technical rubrics.
          </p>
        </div>
        <div className="analytics-metric-grid">
          <article className="metric-card emphasis-card">
            <span className="eyebrow">Projects submitted</span>
            <strong>{submissionsQuery.data?.length ?? 0}</strong>
            <p>Each submission becomes durable evidence for your adaptive path and skill model.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Peer queue</span>
            <strong>{queueQuery.data?.length ?? 0}</strong>
            <p>Review work from other learners to strengthen your evaluation instincts.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Live feedback</span>
            <strong>{liveFeedback?.signal ?? "ready"}</strong>
            <p>Draft analysis updates as your submission becomes more concrete.</p>
          </article>
        </div>
      </section>

      <div className="projects-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Project catalog</p>
              <h2>Pick a practical challenge</h2>
            </div>
          </div>
          <div className="stack">
            {(catalogQuery.data ?? []).map((project) => (
              <button
                className={`builder-scenario-card ${project.slug === selectedProjectSlug ? "is-selected" : ""}`}
                key={project.slug}
                onClick={() => selectProject(project)}
                type="button"
              >
                <span className="eyebrow">{project.difficulty}</span>
                <strong>{project.title}</strong>
                <p>{project.summary}</p>
                <p className="muted">
                  {project.estimated_hours}h | {project.submitted_count} submissions | {project.peer_reviews_received} peer reviews
                </p>
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Submission studio</p>
              <h2>{selectedProject?.title ?? "Select a project"}</h2>
            </div>
            {selectedProject ? <span className="score-pill">{selectedProject.estimated_hours}h</span> : null}
          </div>
          {selectedProject ? (
            <>
              <p className="muted">{selectedProject.deliverable}</p>
              <div className="button-row">
                {selectedProject.linked_lessons.map((lessonSlug) => (
                  <Link className="secondary-button inline-action" href={`/lessons/${lessonSlug}`} key={lessonSlug}>
                    Review {lessonSlug}
                  </Link>
                ))}
              </div>
              <div className="stack">
                {selectedProject.rubric.map((criterion) => (
                  <article className="citation-card" key={criterion.id}>
                    <strong>{criterion.label}</strong>
                    <p>{criterion.description}</p>
                  </article>
                ))}
              </div>
              <form className="stack" onSubmit={handleSubmission}>
                <input
                  value={submission.title}
                  onChange={(event) => setSubmission((current) => ({ ...current, title: event.target.value }))}
                  placeholder="Submission title"
                />
                <textarea
                  className="note-input"
                  rows={6}
                  value={submission.solution_summary}
                  onChange={(event) => {
                    setLiveFeedback(null);
                    setSubmission((current) => ({ ...current, solution_summary: event.target.value }));
                  }}
                  placeholder="Describe the system design, decision boundary, or migration plan you are proposing."
                />
                <textarea
                  className="note-input"
                  rows={6}
                  value={submission.implementation_notes}
                  onChange={(event) => {
                    setLiveFeedback(null);
                    setSubmission((current) => ({ ...current, implementation_notes: event.target.value }));
                  }}
                  placeholder="Explain constraints, validation metrics, baselines, and failure triggers."
                />
                <label>
                  Confidence level
                  <input
                    type="range"
                    min={1}
                    max={5}
                    value={submission.confidence_level}
                    onChange={(event) =>
                      setSubmission((current) => ({ ...current, confidence_level: Number(event.target.value) }))
                    }
                  />
                </label>
                <button className="primary-button" disabled={submitMutation.isPending} type="submit">
                  {submitMutation.isPending ? "Submitting..." : "Submit assignment"}
                </button>
                {submissionError ? <p className="muted">{submissionError}</p> : null}
              </form>
            </>
          ) : null}
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Real-time AI feedback</p>
              <h2>Draft coaching</h2>
            </div>
          </div>
          {liveFeedback ? (
            <div className="stack">
              <article className="insight-card">
                <span className="eyebrow">{liveFeedback.signal}</span>
                <h3>{liveFeedback.confidence_label} confidence</h3>
                <p>{liveFeedback.summary}</p>
                <ul className="goal-list">
                  {liveFeedback.recommended_actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </article>
              {liveFeedback.suggested_resources.map((resource) => (
                <article className="citation-card" key={`${resource.href}-${resource.title}`}>
                  <strong>{resource.title}</strong>
                  <p className="muted">{resource.reason}</p>
                  <p>{resource.summary}</p>
                  <Link className="secondary-button inline-action" href={resource.href}>
                    Open resource
                  </Link>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted">Start drafting the submission. Once the text is substantive, the AI coach will analyze it automatically.</p>
          )}
        </section>
      </div>

      <div className="projects-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">My assignments</p>
              <h2>Submitted evidence</h2>
            </div>
          </div>
          <div className="stack">
            {(submissionsQuery.data ?? []).map((item) => (
              <article className="project-submission-card" key={item.id}>
                <div className="panel-header">
                  <div>
                    <strong>{item.title}</strong>
                    <p className="muted">
                      {item.project_title} | {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>
                  <span className="score-pill">{item.average_peer_score ?? "No score yet"}</span>
                </div>
                <p>{item.solution_summary}</p>
                {item.ai_feedback_summary ? <p className="muted">AI: {item.ai_feedback_summary}</p> : null}
                {item.ai_recommendations.length ? (
                  <ul className="goal-list">
                    {item.ai_recommendations.map((recommendation) => (
                      <li key={recommendation}>{recommendation}</li>
                    ))}
                  </ul>
                ) : null}
                <p className="muted">{item.review_count} peer reviews recorded.</p>
              </article>
            ))}
            {submissionsQuery.data?.length === 0 ? (
              <p className="muted">No project submissions yet. Submit one to create applied evidence for your skill graph.</p>
            ) : null}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Peer review</p>
              <h2>Review queue</h2>
            </div>
          </div>
          <div className="stack">
            {(queueQuery.data ?? []).map((item) => {
              const reviewDraft = reviewDraftFor(item);
              return (
                <article className="project-submission-card" key={item.submission_id}>
                  <strong>{item.title}</strong>
                  <p className="muted">
                    {item.project_title} | submitted by {item.author_id}
                  </p>
                  <p>{item.solution_summary}</p>
                  <p className="muted">{item.implementation_notes}</p>
                  <div className="review-grid">
                    {item.rubric.map((criterion) => (
                      <label key={criterion.id}>
                        {criterion.label}
                        <input
                          type="range"
                          min={1}
                          max={5}
                          value={reviewDraft.rubric_scores[criterion.id] ?? 3}
                          onChange={(event) =>
                            setReviewForms((current) => ({
                              ...current,
                              [item.submission_id]: {
                                ...reviewDraft,
                                rubric_scores: {
                                  ...reviewDraft.rubric_scores,
                                  [criterion.id]: Number(event.target.value),
                                },
                              },
                            }))
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <textarea
                    className="note-input"
                    rows={4}
                    value={reviewDraft.feedback}
                    onChange={(event) =>
                      setReviewForms((current) => ({
                        ...current,
                        [item.submission_id]: {
                          ...reviewDraft,
                          feedback: event.target.value,
                        },
                      }))
                    }
                    placeholder="Give specific technical feedback tied to the rubric."
                  />
                  <button
                    className="secondary-button"
                    disabled={reviewMutation.isPending}
                    onClick={() => reviewMutation.mutate({ submissionId: item.submission_id, draft: reviewDraft })}
                    type="button"
                  >
                    {reviewMutation.isPending ? "Submitting..." : "Submit review"}
                  </button>
                </article>
              );
            })}
            {reviewMutation.isError ? (
              <p className="muted">{toErrorMessage(reviewMutation.error, "Could not submit the peer review.")}</p>
            ) : null}
            {queueQuery.data?.length === 0 ? (
              <p className="muted">No peer submissions are waiting for review yet.</p>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
