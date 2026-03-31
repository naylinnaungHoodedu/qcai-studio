import Link from "next/link";
import { ReactNode } from "react";

import { PrimaryNav } from "@/components/primary-nav";
import { SiteFooter } from "@/components/site-footer";
import { TeachingAssistantChat } from "@/components/teaching-assistant-chat";

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
        <PrimaryNav />
      </header>
      <main id="main-content">{children}</main>
      <SiteFooter />
      <TeachingAssistantChat />
    </div>
  );
}
