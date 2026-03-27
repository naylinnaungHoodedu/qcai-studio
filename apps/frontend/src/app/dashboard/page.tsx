import { LearningDashboardView } from "@/components/learning-dashboard";
import {
  fetchAdaptivePath,
  fetchCourseOverview,
  fetchCourseProgress,
  fetchLearningDashboard,
  fetchMe,
  fetchSkillGapReport,
} from "@/lib/api";


export default async function DashboardPage() {
  const [course, progress, user, dashboard, adaptivePath, gapReport] = await Promise.all([
    fetchCourseOverview(),
    fetchCourseProgress(),
    fetchMe(),
    fetchLearningDashboard(),
    fetchAdaptivePath(),
    fetchSkillGapReport(),
  ]);

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
