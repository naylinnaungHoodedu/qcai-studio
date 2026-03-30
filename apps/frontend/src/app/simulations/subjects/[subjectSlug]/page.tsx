import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { AcademySubjectBrowser } from "@/components/academy-simulation-browser";
import { StructuredData } from "@/components/structured-data";
import {
  ACADEMY_SIMULATION_RECORDS,
  ACADEMY_SUBJECT_RECORDS,
  getAcademySubjectBySlug,
} from "@/lib/academy-simulations";
import { buildBreadcrumbStructuredData, buildPageMetadata } from "@/lib/metadata";
import { SITE_URL } from "@/lib/site";

type AcademySubjectPageProps = {
  params: Promise<{ subjectSlug: string }>;
};

export function generateStaticParams() {
  return ACADEMY_SUBJECT_RECORDS.map((subject) => ({
    subjectSlug: subject.slug,
  }));
}

export async function generateMetadata({
  params,
}: AcademySubjectPageProps): Promise<Metadata> {
  const { subjectSlug } = await params;
  const subject = getAcademySubjectBySlug(subjectSlug);

  if (!subject) {
    return buildPageMetadata({
      title: "Simulation subject unavailable",
      description: "The requested simulation subject could not be found.",
      path: `/simulations/subjects/${subjectSlug}`,
      index: false,
    });
  }

  return buildPageMetadata({
    title: subject.title,
    description: subject.summary,
    path: subject.href,
    type: "article",
  });
}

export default async function AcademySubjectPage({
  params,
}: AcademySubjectPageProps) {
  const { subjectSlug } = await params;
  const subject = getAcademySubjectBySlug(subjectSlug);

  if (!subject) {
    notFound();
  }

  const subjectSimulations = ACADEMY_SIMULATION_RECORDS.filter(
    (simulation) => simulation.subjectSlug === subject.slug,
  );

  const structuredData = [
    buildBreadcrumbStructuredData([
      { name: "Home", path: "/" },
      { name: "Simulations", path: "/simulations" },
      { name: subject.title, path: subject.href },
    ]),
    {
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: subject.title,
      description: subject.summary,
      url: `${SITE_URL}${subject.href}`,
    },
    {
      "@context": "https://schema.org",
      "@type": "ItemList",
      itemListOrder: "https://schema.org/ItemListOrderAscending",
      numberOfItems: subjectSimulations.length,
      itemListElement: subjectSimulations.map((simulation, index) => ({
        "@type": "ListItem",
        position: index + 1,
        name: simulation.title,
        url: `${SITE_URL}${simulation.href}`,
      })),
    },
  ];

  return (
    <>
      <StructuredData data={structuredData} id={`academy-subject-${subject.slug}-jsonld`} />
      <AcademySubjectBrowser
        subject={subject}
        subjectSimulations={subjectSimulations}
        subjects={ACADEMY_SUBJECT_RECORDS}
      />
    </>
  );
}
