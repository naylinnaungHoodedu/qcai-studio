import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SimulationStudio } from "@/components/simulation-studio";
import { StructuredData } from "@/components/structured-data";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import {
  getSimulationBySlug,
  SIMULATION_MODULE_ENTRIES,
  SIMULATION_RECORDS,
} from "@/lib/simulations";
import { SITE_URL } from "@/lib/site";

type SimulationPageProps = {
  params: Promise<{ slug: string }>;
};

export function generateStaticParams() {
  return SIMULATION_RECORDS.map((simulation) => ({
    slug: simulation.slug,
  }));
}

export async function generateMetadata({ params }: SimulationPageProps): Promise<Metadata> {
  const { slug } = await params;
  const simulation = getSimulationBySlug(slug);

  if (!simulation) {
    return buildPageMetadata({
      title: "Simulation unavailable",
      description: "The requested QC+AI simulation could not be found.",
      path: `/simulations/${slug}`,
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

export default async function SimulationPage({ params }: SimulationPageProps) {
  const { slug } = await params;
  const simulation = getSimulationBySlug(slug);

  if (!simulation) {
    notFound();
  }

  const structuredData = [
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "Simulations", path: "/simulations" },
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
      about: simulation.moduleTitle,
    },
  ];

  return (
    <>
      <StructuredData data={structuredData} id={`simulation-${simulation.slug}-jsonld`} />
      <SimulationStudio modules={SIMULATION_MODULE_ENTRIES} simulation={simulation} />
    </>
  );
}
