import { LearningDashboardView } from "@/components/learning-dashboard";
import { PageErrorState } from "@/components/page-state";
import {
  fetchAdaptivePath,
  fetchCourseOverview,
  fetchCourseProgress,
  fetchLearningDashboard,
  fetchMe,
  fetchSkillGapReport,
} from "@/lib/api";


export default async function DashboardPage() {
  const data = await Promise.all([
    fetchCourseOverview(),
    fetchCourseProgress(),
    fetchMe(),
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
  const [course, progress, user, dashboard, adaptivePath, gapReport] = data;

  return (
    <LearningDashboardView
      course={course}
      progress={progress}
      user={user}
      initialDashboard={dashboard}
      initialPath={adaptivePath}
      initialGapReport={gapReport}
    />
  );
}
