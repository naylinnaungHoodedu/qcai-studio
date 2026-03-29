import type { Metadata } from "next";

import { SITE_URL } from "@/lib/site";

const SITE_NAME = "QC+AI Studio";
const OPEN_GRAPH_IMAGE = "/opengraph-image";
const TWITTER_IMAGE = "/twitter-image";

type BuildPageMetadataOptions = {
  title?: string;
  description: string;
  path: string;
  index?: boolean;
  type?: "website" | "article";
};

type BreadcrumbItem = {
  name: string;
  path: string;
};

export function buildPageMetadata({
  title,
  description,
  path,
  index = true,
  type = "website",
}: BuildPageMetadataOptions): Metadata {
  const canonicalPath = path.startsWith("/") ? path : `/${path}`;
  const resolvedTitle = title ?? SITE_NAME;

  return {
    title,
    description,
    alternates: {
      canonical: canonicalPath,
    },
    openGraph: {
      title: resolvedTitle,
      description,
      url: canonicalPath,
      siteName: SITE_NAME,
      type,
      images: [
        {
          url: OPEN_GRAPH_IMAGE,
          width: 1200,
          height: 630,
          alt: `${resolvedTitle} | ${SITE_NAME}`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: resolvedTitle,
      description,
      images: [TWITTER_IMAGE],
    },
    robots: index
      ? undefined
      : {
          index: false,
          follow: false,
          googleBot: {
            index: false,
            follow: false,
          },
        },
  };
}

export function buildBreadcrumbStructuredData(items: BreadcrumbItem[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: `${SITE_URL}${item.path}`,
    })),
  };
}
