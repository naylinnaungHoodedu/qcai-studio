import { PageErrorState } from "@/components/page-state";
import { ProjectsStudio } from "@/components/projects-studio";
import { fetchMyProjectSubmissions, fetchProjectCatalog, fetchProjectReviewQueue } from "@/lib/api";


export default async function ProjectsPage() {
  const data = await Promise.all([
    fetchProjectCatalog(),
    fetchMyProjectSubmissions(),
    fetchProjectReviewQueue(),
  ]).catch(() => null);

  if (!data) {
    return (
      <PageErrorState
        title="The project studio could not be loaded"
        detail="Project catalog, submissions, or review queue data failed to load for this request."
      />
    );
  }
  const [catalog, submissions, queue] = data;

  return <ProjectsStudio initialCatalog={catalog} initialSubmissions={submissions} initialQueue={queue} />;
}
