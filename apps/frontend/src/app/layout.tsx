import type { Metadata } from "next";
import { connection } from "next/server";
import { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";
import { SITE_URL } from "@/lib/site";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "QC+AI Studio",
    template: "%s | QC+AI Studio",
  },
  description:
    "Interactive learning environment for quantum computing and artificial intelligence under hardware constraints.",
  openGraph: {
    title: "QC+AI Studio",
    description:
      "Interactive learning environment for quantum computing and artificial intelligence under hardware constraints.",
    url: SITE_URL,
    siteName: "QC+AI Studio",
    type: "website",
    images: [
      {
        url: "/opengraph-image",
        width: 1200,
        height: 630,
        alt: "QC+AI Studio social preview",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "QC+AI Studio",
    description:
      "Interactive learning environment for quantum computing and artificial intelligence under hardware constraints.",
    images: ["/twitter-image"],
  },
};

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  await connection();
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
