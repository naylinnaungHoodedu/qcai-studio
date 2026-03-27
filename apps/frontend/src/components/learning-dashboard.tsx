"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import {
  createLearningCheckIn,
  fetchAdaptivePath,
  fetchLearningDashboard,
  fetchSkillGapReport,
  requestRealtimeFeedback,
  updateLearnerProfile,
} from "@/lib/api";
import {
  AdaptivePath,
  CourseOverview,
  CourseProgress,
  LearningDashboard,
  ModuleProgress,
  RealtimeFeedback,
  SkillGapReport,
} from "@/lib/types";


const ROLE_OPTIONS = [
  "Quantum ML Engineer",
  "Quantum Optimization Analyst",
  "QC+AI Product Strategist",
  "Applied Quantum Systems Engineer",
];

const PACE_OPTIONS = ["balanced", "accelerate", "stabilize"];

const SKILL_LABELS: Array<{ id: string; label: string }> = [
  { id: "quantum_hardware", label: "Quantum hardware" },
  { id: "hybrid_architecture", label: "Hybrid architecture" },
  { id: "optimization", label: "Optimization" },
  { id: "applied_qcai", label: "Applied QC+AI" },
  { id: "representation_xai", label: "Representation and XAI" },
  { id: "industry_strategy", label: "Industry strategy" },
  { id: "roadmapping", label: "Roadmapping" },
];

const SKILL_HELP: Record<string, string> = {
  quantum_hardware: "How well you reason about routing, noise, qubit limits, and executable circuit realism.",
  hybrid_architecture: "How clearly you can place a bounded quantum stage inside a wider classical workflow.",
  optimization: "How well you reformulate constrained problems, reason about QUBO structure, and compare baselines.",
  applied_qcai: "How well you evaluate realistic application-fit for hybrid QC+AI systems.",
  representation_xai: "How well you reason about features, explainability, kernels, and representation quality.",
  industry_strategy: "How well you judge commercial readiness, migration timing, and sector-specific value.",
  roadmapping: "How well you translate technical capability into staged execution plans and future direction.",
};

type LearningDashboardProps = {
  course: CourseOverview;
  progress: CourseProgress;
  initialDashboard: LearningDashboard;
  initialPath: AdaptivePath;
  initialGapReport: SkillGapReport;
};

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function moduleProgressMap(progress: CourseProgress): Map<string, ModuleProgress> {
  return new Map(progress.modules.map((item) => [item.module_slug, item]));
}

export function LearningDashboardView({
  course,
  progress,
  initialDashboard,
  initialPath,
  initialGapReport,
}: LearningDashboardProps) {
  const queryClient = useQueryClient();
  const [profileForm, setProfileForm] = useState(initialDashboard.profile);
  const [checkIn, setCheckIn] = useState({
    motivation_level: 3,
    focus_level: 3,
    energy_level: 3,
    session_minutes: 30,
    today_goal: "",
    blocker: "",
  });
  const [coachPrompt, setCoachPrompt] = useState("");
  const [coachResult, setCoachResult] = useState<RealtimeFeedback | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const dashboardQuery = useQuery({
    queryKey: ["learning-dashboard"],
    queryFn: fetchLearningDashboard,
    initialData: initialDashboard,
  });
  const pathQuery = useQuery({
    queryKey: ["adaptive-path"],
    queryFn: fetchAdaptivePath,
    initialData: initialPath,
  });
  const gapQuery = useQuery({
    queryKey: ["skill-gap"],
    queryFn: fetchSkillGapReport,
    initialData: initialGapReport,
  });

  const saveProfileMutation = useMutation({
    mutationFn: () =>
      updateLearnerProfile({
        target_role: profileForm.target_role,
        weekly_goal_hours: profileForm.weekly_goal_hours,
        preferred_pace: profileForm.preferred_pace,
        focus_area: profileForm.focus_area ?? null,
        self_ratings: profileForm.self_ratings,
      }),
    onSuccess: (nextProfile) => {
      setProfileForm(nextProfile);
      void queryClient.invalidateQueries({ queryKey: ["learning-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["adaptive-path"] });
      void queryClient.invalidateQueries({ queryKey: ["skill-gap"] });
    },
  });

  const checkInMutation = useMutation({
    mutationFn: () => createLearningCheckIn(checkIn),
    onSuccess: () => {
      setCheckIn({
        motivation_level: 3,
        focus_level: 3,
        energy_level: 3,
        session_minutes: 30,
        today_goal: "",
        blocker: "",
      });
      void queryClient.invalidateQueries({ queryKey: ["learning-dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["adaptive-path"] });
    },
  });

  const coachMutation = useMutation({
    mutationFn: () =>
      requestRealtimeFeedback({
        context_type: "study_blocker",
        content: coachPrompt.trim(),
      }),
    onSuccess: (result) => {
      setFeedbackError(null);
      setCoachResult(result);
    },
    onError: (error) => {
      setFeedbackError(toErrorMessage(error, "Could not generate coaching right now."));
    },
  });

  const dashboard = dashboardQuery.data;
  const adaptivePath = pathQuery.data;
  const gapReport = gapQuery.data;
  const modulesBySlug = moduleProgressMap(progress);
  const liveCoach = coachResult ?? dashboard.coach_feedback;
  const needsSelfRatingBaseline = Object.values(profileForm.self_ratings).every((value) => value === 2);

  function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    saveProfileMutation.mutate();
  }

  function handleCheckInSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    checkInMutation.mutate();
  }

  function handleCoachSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!coachPrompt.trim()) {
      return;
    }
    coachMutation.mutate();
  }

  return (
    <div className="page-stack">
      <section className="section-block analytics-hero">
        <div className="section-heading">
          <p className="eyebrow">Learning Intelligence</p>
          <h1>Your learning dashboard</h1>
          <p>
            Progress, motivation, focus, adaptive pacing, role-fit skill gaps, and AI coaching are all derived from your
            real learning activity across lessons, games, and projects.
          </p>
        </div>
        <div className="analytics-metric-grid">
          <article className="metric-card emphasis-card">
            <span className="eyebrow">Progress</span>
            <strong>{dashboard.metrics.progress_percent}%</strong>
            <p>{dashboard.metrics.completed_lessons} lessons completed across the QC+AI course.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Motivation</span>
            <strong>{dashboard.metrics.motivation_score}</strong>
            <p>Momentum informed by your recent check-ins and completion rhythm.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Focus</span>
            <strong>{dashboard.metrics.focus_score}</strong>
            <p>{dashboard.metrics.active_streak_days} active days in the current streak.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Goal pacing</span>
            <strong>{dashboard.metrics.weekly_goal_progress_percent}%</strong>
            <p>{dashboard.metrics.weekly_goal_hours} planned hours this week.</p>
          </article>
        </div>
      </section>

      {needsSelfRatingBaseline ? (
        <section className="panel onboarding-banner">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Onboarding</p>
              <h2>Set your skill baseline</h2>
            </div>
            <a className="secondary-button inline-action" href="#profile-tuning">
              Open self-ratings
            </a>
          </div>
          <p>
            Your adaptive path and skill-gap analysis are still leaning on default self-ratings. Set a sharper baseline
            so the recommendations and role-fit model track your actual starting point.
          </p>
        </section>
      ) : null}

      <div className="insight-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Analytics dashboard</p>
              <h2>Progress, focus, and motivation trends</h2>
            </div>
            <span className="score-pill">Consistency {dashboard.metrics.consistency_score}</span>
          </div>
          <div className="analytics-band">
            {dashboard.activity.map((point) => (
              <div className="activity-bar-card" key={point.date}>
                <div className="activity-bar-track">
                  <span style={{ height: `${Math.max(14, point.events * 14)}px` }} />
                </div>
                <strong>{point.events}</strong>
                <span className="muted">{point.label}</span>
                <span className="muted">
                  F {point.focus_level ?? "-"} / M {point.motivation_level ?? "-"}
                </span>
              </div>
            ))}
          </div>
          <div className="stack">
            {dashboard.module_insights.map((insight) => (
              <article className="insight-card" key={insight.module_slug}>
                <div className="panel-header">
                  <div>
                    <span className="eyebrow">{insight.confidence_label}</span>
                    <h3>{insight.module_title}</h3>
                  </div>
                  <span className="score-pill">{insight.mastery_percent}% mastery</span>
                </div>
                <p className="muted">{insight.recommendation}</p>
                {insight.risk_flag ? <p className="muted">{insight.risk_flag}</p> : null}
              </article>
            ))}
          </div>
          <div className="stack">
            <div className="panel-header">
              <div>
                <p className="eyebrow">90-day streak</p>
                <h3>Study heat map</h3>
              </div>
            </div>
            <div className="heatmap-grid" role="list">
              {dashboard.heatmap.map((point) => (
                <div
                  className={`heatmap-cell intensity-${point.intensity}`}
                  key={point.date}
                  role="listitem"
                  title={`${point.date}: ${point.events} learning events${point.goal_minutes ? `, ${point.goal_minutes} focus minutes` : ""}`}
                />
              ))}
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Check-in</p>
              <h2>Track energy, focus, and blockers</h2>
            </div>
          </div>
          <form className="stack" onSubmit={handleCheckInSubmit}>
            <div className="analytics-form-grid">
              <label>
                Motivation
                <input
                  type="range"
                  min={1}
                  max={5}
                  value={checkIn.motivation_level}
                  onChange={(event) =>
                    setCheckIn((current) => ({ ...current, motivation_level: Number(event.target.value) }))
                  }
                />
              </label>
              <label>
                Focus
                <input
                  type="range"
                  min={1}
                  max={5}
                  value={checkIn.focus_level}
                  onChange={(event) => setCheckIn((current) => ({ ...current, focus_level: Number(event.target.value) }))}
                />
              </label>
              <label>
                Energy
                <input
                  type="range"
                  min={1}
                  max={5}
                  value={checkIn.energy_level}
                  onChange={(event) =>
                    setCheckIn((current) => ({ ...current, energy_level: Number(event.target.value) }))
                  }
                />
              </label>
              <label>
                Session minutes
                <input
                  type="number"
                  min={10}
                  max={240}
                  value={checkIn.session_minutes}
                  onChange={(event) =>
                    setCheckIn((current) => ({ ...current, session_minutes: Number(event.target.value) }))
                  }
                />
              </label>
            </div>
            <textarea
              className="note-input"
              rows={3}
              placeholder="What is the most important outcome for this session?"
              value={checkIn.today_goal}
              onChange={(event) => setCheckIn((current) => ({ ...current, today_goal: event.target.value }))}
            />
            <textarea
              className="note-input"
              rows={3}
              placeholder="What is slowing you down right now?"
              value={checkIn.blocker}
              onChange={(event) => setCheckIn((current) => ({ ...current, blocker: event.target.value }))}
            />
            <button className="primary-button" disabled={checkInMutation.isPending} type="submit">
              {checkInMutation.isPending ? "Saving..." : "Save check-in"}
            </button>
            {checkInMutation.isError ? (
              <p className="muted">{toErrorMessage(checkInMutation.error, "Could not save the check-in.")}</p>
            ) : null}
          </form>
          <div className="stack">
            {dashboard.pulses.map((pulse) => (
              <article className="note-card" key={pulse.id}>
                <strong>
                  Focus {pulse.focus_level}/5, motivation {pulse.motivation_level}/5, energy {pulse.energy_level}/5
                </strong>
                <p className="muted">
                  {pulse.session_minutes} min session | {new Date(pulse.created_at).toLocaleString()}
                </p>
                {pulse.today_goal ? <p>{pulse.today_goal}</p> : null}
                {pulse.blocker ? <p className="muted">Blocker: {pulse.blocker}</p> : null}
              </article>
            ))}
          </div>
        </section>
      </div>

      <div className="insight-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Adaptive learning path</p>
              <h2>AI-personalized next steps</h2>
            </div>
            <span className="status-pill in_progress">{adaptivePath.pace_mode}</span>
          </div>
          <p className="muted">{adaptivePath.adaptation_summary}</p>
          <div className="stack">
            {adaptivePath.steps.map((step) => (
              <article className="path-step-card" key={step.step_number}>
                <div className="panel-header">
                  <div>
                    <span className="eyebrow">Step {step.step_number}</span>
                    <h3>{step.title}</h3>
                  </div>
                  <span className="score-pill">{step.estimated_minutes} min</span>
                </div>
                <p>{step.summary}</p>
                <p className="muted">{step.reason}</p>
                <div className="button-row">
                  <Link className="primary-button" href={step.href}>
                    Open step
                  </Link>
                  <span className="status-pill completed">{step.intensity}</span>
                  <span className="status-pill">{step.recommendation_type}</span>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">AI coach</p>
              <h2>Real-time feedback and recommendations</h2>
            </div>
          </div>
          <form className="stack" onSubmit={handleCoachSubmit}>
            <textarea
              className="note-input"
              rows={5}
              placeholder="Describe the concept, blocker, or draft plan you want feedback on."
              value={coachPrompt}
              onChange={(event) => setCoachPrompt(event.target.value)}
            />
            <button className="secondary-button" disabled={coachMutation.isPending} type="submit">
              {coachMutation.isPending ? "Analyzing..." : "Run AI coaching"}
            </button>
          </form>
          {feedbackError ? <p className="muted">{feedbackError}</p> : null}
          <article className="insight-card">
            <span className="eyebrow">{liveCoach.signal}</span>
            <h3>{liveCoach.confidence_label} confidence</h3>
            <p>{liveCoach.summary}</p>
            <ul className="goal-list">
              {liveCoach.recommended_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          </article>
          <div className="stack">
            {liveCoach.suggested_resources.map((resource) => (
              <article className="citation-card" key={`${resource.href}-${resource.title}`}>
                <strong>{resource.title}</strong>
                <p className="muted">
                  {resource.reason} | {resource.urgency}
                </p>
                <p>{resource.summary}</p>
                <Link className="secondary-button inline-action" href={resource.href}>
                  Open recommendation
                </Link>
              </article>
            ))}
          </div>
        </section>
      </div>

      <div className="insight-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Skill gap analysis</p>
              <h2>Role-fit readiness</h2>
            </div>
            <span className="score-pill">{gapReport.readiness_percent}% ready</span>
          </div>
          <p className="muted">{gapReport.role_summary}</p>
          <div className="stack">
            {gapReport.gaps.map((gap) => (
              <article className="skill-gap-card" key={gap.skill_id}>
                <div className="panel-header">
                  <div>
                    <strong>{gap.label}</strong>
                    <p className="muted">{gap.evidence}</p>
                  </div>
                  <span className="score-pill">Gap {gap.gap}</span>
                </div>
                <div className="module-progress">
                  <div className="module-progress-track">
                    <span style={{ width: `${Math.min(100, (gap.current_level / gap.target_level) * 100)}%` }} />
                  </div>
                  <p className="muted">
                    Current {gap.current_level}/5 | target {gap.target_level}/5
                  </p>
                </div>
                <ul className="goal-list">
                  {gap.recommended_actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="panel" id="profile-tuning">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Profile tuning</p>
              <h2>Update role targets and pacing</h2>
            </div>
          </div>
          <form className="stack" onSubmit={handleProfileSubmit}>
            <label>
              Target role
              <select
                value={profileForm.target_role}
                onChange={(event) => setProfileForm((current) => ({ ...current, target_role: event.target.value }))}
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Preferred pace
              <select
                value={profileForm.preferred_pace}
                onChange={(event) => setProfileForm((current) => ({ ...current, preferred_pace: event.target.value }))}
              >
                {PACE_OPTIONS.map((pace) => (
                  <option key={pace} value={pace}>
                    {pace}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Weekly goal hours
              <input
                type="number"
                min={1}
                max={40}
                value={profileForm.weekly_goal_hours}
                onChange={(event) =>
                  setProfileForm((current) => ({ ...current, weekly_goal_hours: Number(event.target.value) }))
                }
              />
            </label>
            <div className="analytics-form-grid">
              {SKILL_LABELS.map((skill) => (
                <label key={skill.id}>
                  <span title={SKILL_HELP[skill.id]}>{skill.label}</span>
                  <input
                    type="range"
                    min={1}
                    max={5}
                    value={profileForm.self_ratings[skill.id] ?? 2}
                    onChange={(event) =>
                      setProfileForm((current) => ({
                        ...current,
                        self_ratings: {
                          ...current.self_ratings,
                          [skill.id]: Number(event.target.value),
                        },
                      }))
                    }
                  />
                  <span className="muted">{SKILL_HELP[skill.id]}</span>
                </label>
              ))}
            </div>
            <button className="primary-button" disabled={saveProfileMutation.isPending} type="submit">
              {saveProfileMutation.isPending ? "Saving..." : "Save profile"}
            </button>
            {saveProfileMutation.isError ? (
              <p className="muted">{toErrorMessage(saveProfileMutation.error, "Could not save the learner profile.")}</p>
            ) : null}
          </form>
          <div className="stack">
            {gapReport.recommendations.map((recommendation) => (
              <article className="citation-card" key={`${recommendation.href}-${recommendation.title}`}>
                <strong>{recommendation.title}</strong>
                <p className="muted">{recommendation.reason}</p>
                <p>{recommendation.summary}</p>
                <Link className="secondary-button inline-action" href={recommendation.href}>
                  Open
                </Link>
              </article>
            ))}
          </div>
        </section>
      </div>

      <div className="two-column-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Course map</p>
              <h2>Current module state</h2>
            </div>
          </div>
          <div className="lesson-list">
            {course.modules.map((module, index) => {
              const moduleProgress = modulesBySlug.get(module.slug);
              return (
                <article className="lesson-card" key={module.slug}>
                  <div>
                    <p className="eyebrow">Step {index + 1}</p>
                    <h3>{module.title}</h3>
                    <p>{module.summary}</p>
                    {moduleProgress ? (
                      <p className="muted">
                        {moduleProgress.status.replace("_", " ")} | {moduleProgress.progress_percent}% progress
                      </p>
                    ) : null}
                    {moduleProgress?.status === "completed" ? (
                      <p className="muted">Module complete. Update your skill ratings to sharpen the adaptive path.</p>
                    ) : null}
                  </div>
                  <div className="lesson-actions">
                    <Link className="primary-button" href={`/modules/${module.slug}`}>
                      Continue
                    </Link>
                    {moduleProgress?.status === "completed" ? (
                      <a className="secondary-button" href="#profile-tuning">
                        Update ratings
                      </a>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Evidence trail</p>
              <h2>Recent notes and quiz history</h2>
            </div>
          </div>
          <div className="stack">
            {progress.recent_notes.map((note) => (
              <article className="note-card" key={note.id}>
                <p>{note.body}</p>
                <span className="muted">
                  {note.lesson_slug} | {new Date(note.created_at).toLocaleString()}
                </span>
              </article>
            ))}
            {progress.recent_quiz_attempts.map((attempt) => (
              <article className="citation-card" key={attempt.id}>
                <strong>{attempt.lesson_slug}</strong>
                <p className="muted">
                  Score {attempt.score} | {new Date(attempt.created_at).toLocaleString()}
                </p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
