import type { Metadata } from "next";

const SITE_NAME = "QC+AI Studio";

type BuildPageMetadataOptions = {
  title?: string;
  description: string;
  path: string;
  index?: boolean;
  type?: "website" | "article";
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
    },
    twitter: {
      card: "summary_large_image",
      title: resolvedTitle,
      description,
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
