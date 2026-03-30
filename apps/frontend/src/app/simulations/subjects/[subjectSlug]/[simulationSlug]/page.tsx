import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AcademySimulationStudio } from "@/components/academy-simulation-studio";
import { StructuredData } from "@/components/structured-data";
import {
  ACADEMY_SIMULATION_RECORDS,
  ACADEMY_SUBJECT_RECORDS,
  getAcademySimulationBySlug,
  getAcademySubjectBySlug,
} from "@/lib/academy-simulations";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { SITE_URL } from "@/lib/site";

type AcademySimulationPageProps = {
  params: Promise<{ subjectSlug: string; simulationSlug: string }>;
};

export function generateStaticParams() {
  return ACADEMY_SIMULATION_RECORDS.map((simulation) => ({
    subjectSlug: simulation.subjectSlug,
    simulationSlug: simulation.slug,
  }));
}

export async function generateMetadata({
  params,
}: AcademySimulationPageProps): Promise<Metadata> {
  const { subjectSlug, simulationSlug } = await params;
  const simulation = getAcademySimulationBySlug(subjectSlug, simulationSlug);

  if (!simulation) {
    return buildPageMetadata({
      title: "Simulation unavailable",
      description: "The requested academy simulation could not be found.",
      path: `/simulations/subjects/${subjectSlug}/${simulationSlug}`,
      index: false,
    });
  }

  return buildPageMetadata({
    title: simulation.title,
    description: simulation.summary,
    path: simulation.href,
    type: "article",
  });
}

export default async function AcademySimulationPage({
  params,
}: AcademySimulationPageProps) {
  const { subjectSlug, simulationSlug } = await params;
  const subject = getAcademySubjectBySlug(subjectSlug);
  const simulation = getAcademySimulationBySlug(subjectSlug, simulationSlug);

  if (!subject || !simulation) {
    notFound();
  }

  const subjectSimulations = ACADEMY_SIMULATION_RECORDS.filter(
    (item) => item.subjectSlug === subject.slug,
  );

  const structuredData = [
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "Simulations", path: "/simulations" },
      { name: subject.title, path: subject.href },
      { name: simulation.title, path: simulation.href },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "LearningResource",
      name: simulation.title,
      description: simulation.summary,
      educationalLevel: simulation.difficulty,
      url: `${SITE_URL}${simulation.href}`,
      learningResourceType: "Interactive simulation",
      about: subject.title,
    },
  ];

  return (
    <>
      <StructuredData data={structuredData} id={`academy-simulation-${simulation.slug}-jsonld`} />
      <AcademySimulationStudio
        simulation={simulation}
        subject={subject}
        subjectSimulations={subjectSimulations}
        subjects={ACADEMY_SUBJECT_RECORDS}
      />
    </>
  );
}
