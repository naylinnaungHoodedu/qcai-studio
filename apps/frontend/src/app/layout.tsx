import type { Metadata } from "next";
import { ReactNode } from "react";
import { headers } from "next/headers";
import { Space_Grotesk } from "next/font/google";

import { AppShell } from "@/components/app-shell";
import { Providers } from "@/components/providers";
import { WebVitalsReporter } from "@/components/web-vitals-reporter";
import { SITE_URL } from "@/lib/site";

import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-ui",
});

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
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link href="https://api.qantumlearn.academy" rel="preconnect" crossOrigin="" />
        <link href="https://api.qantumlearn.academy" rel="dns-prefetch" />
      </head>
      <body className={spaceGrotesk.variable} nonce={nonce}>
        <Providers>
          <WebVitalsReporter />
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
