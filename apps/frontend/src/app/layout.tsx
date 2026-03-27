import type { Metadata } from "next";
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
  },
  twitter: {
    card: "summary_large_image",
    title: "QC+AI Studio",
    description:
      "Interactive learning environment for quantum computing and artificial intelligence under hardware constraints.",
  },
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
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
