import Link from "next/link";
import { ReactNode } from "react";

import { SiteFooter } from "@/components/site-footer";
import { PRIMARY_NAV_ITEMS } from "@/lib/navigation";

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
        <nav className="site-nav" aria-label="Primary">
          {PRIMARY_NAV_ITEMS.map((item) =>
            "children" in item ? (
              <details className="site-nav-group" key={item.label}>
                <summary>{item.label}</summary>
                <div className="site-subnav" role="group" aria-label={`${item.label} links`}>
                  {item.children.map((child) => (
                    <Link href={child.href} key={child.href}>
                      {child.label}
                    </Link>
                  ))}
                </div>
              </details>
            ) : (
              <Link href={item.href} key={item.href}>
                {item.label}
              </Link>
            ),
          )}
        </nav>
      </header>
      <main id="main-content">{children}</main>
      <SiteFooter />
    </div>
  );
}
