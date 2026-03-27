import Link from "next/link";
import { ReactNode } from "react";

import { SiteFooter } from "@/components/site-footer";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div>
          <Link href="/" className="brand-mark">
            QC+AI Studio
          </Link>
          <p className="brand-subtitle">
            Hardware-constrained learning for quantum computing and artificial intelligence
          </p>
        </div>
        <nav className="site-nav">
          <Link href="/">Overview</Link>
          <Link href="/syllabus">Syllabus</Link>
          <Link href="/projects">Projects</Link>
          <Link href="/arena">Arena</Link>
          <Link href="/builder">Builder</Link>
          <Link href="/dashboard">Dashboard</Link>
          <Link href="/search">Search</Link>
          <Link href="/account">Account</Link>
        </nav>
      </header>
      <main id="main-content">{children}</main>
      <SiteFooter />
    </div>
  );
}
