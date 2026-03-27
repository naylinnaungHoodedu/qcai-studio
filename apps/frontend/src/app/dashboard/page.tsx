import type { Metadata } from "next";

import { LearningDashboardView } from "@/components/learning-dashboard";
import { PageErrorState } from "@/components/page-state";
import {
  fetchAdaptivePath,
  fetchCourseOverview,
  fetchCourseProgress,
  fetchLearningDashboard,
  fetchSkillGapReport,
} from "@/lib/api";
import { buildPageMetadata } from "@/lib/metadata";
import { CourseProgress, LearningDashboard } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = buildPageMetadata({
  title: "Learning Dashboard",
  description:
    "Private learner analytics workspace with progress, pacing, skill-gap, and coaching signals for QC+AI study.",
  path: "/dashboard",
  index: false,
});

const PRIVATE_LEARNER_LABEL = "private-learner";

function sanitizeProgressPayload(progress: CourseProgress): CourseProgress {
  return {
    ...progress,
    user_id: PRIVATE_LEARNER_LABEL,
  };
}

function sanitizeDashboardPayload(dashboard: LearningDashboard): LearningDashboard {
  return {
    ...dashboard,
    profile: {
      ...dashboard.profile,
      user_id: PRIVATE_LEARNER_LABEL,
    },
  };
}

export default async function DashboardPage() {
  const data = await Promise.all([
    fetchCourseOverview(),
    fetchCourseProgress(),
    fetchLearningDashboard(),
    fetchAdaptivePath(),
    fetchSkillGapReport(),
  ]).catch(() => null);

  if (!data) {
    return (
      <PageErrorState
        title="The dashboard could not be loaded"
        detail="One or more learner intelligence endpoints failed, so the analytics workspace is in a safe fallback state."
      />
    );
  }
  const [course, progress, dashboard, adaptivePath, gapReport] = data;

  return (
    <LearningDashboardView
      course={course}
      progress={sanitizeProgressPayload(progress)}
      initialDashboard={sanitizeDashboardPayload(dashboard)}
      initialPath={adaptivePath}
      initialGapReport={gapReport}
    />
  );
}
