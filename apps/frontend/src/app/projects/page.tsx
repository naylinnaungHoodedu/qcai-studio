import { ProjectsStudio } from "@/components/projects-studio";
import { fetchMyProjectSubmissions, fetchProjectCatalog, fetchProjectReviewQueue } from "@/lib/api";


export default async function ProjectsPage() {
  const [catalog, submissions, queue] = await Promise.all([
    fetchProjectCatalog(),
    fetchMyProjectSubmissions(),
    fetchProjectReviewQueue(),
  ]);

  return <ProjectsStudio initialCatalog={catalog} initialSubmissions={submissions} initialQueue={queue} />;
}
