"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { closeOpenNavGroups } from "@/lib/nav-disclosure";
import { PRIMARY_NAV_ITEMS } from "@/lib/navigation";

export function PrimaryNav() {
  const pathname = usePathname();
  const navRef = useRef<HTMLElement>(null);

  function handleNavAction() {
    closeOpenNavGroups(navRef.current);
  }

  useEffect(() => {
    closeOpenNavGroups(navRef.current);
  }, [pathname]);

  return (
    <nav className="site-nav" aria-label="Primary" ref={navRef}>
      {PRIMARY_NAV_ITEMS.map((item) =>
        "children" in item ? (
          <details className="site-nav-group" key={item.label}>
            <summary>{item.label}</summary>
            <div className="site-subnav" role="group" aria-label={`${item.label} links`}>
              {item.children.map((child) => (
                <Link href={child.href} key={child.href} onClick={handleNavAction}>
                  {child.label}
                </Link>
              ))}
            </div>
          </details>
        ) : (
          <Link href={item.href} key={item.href} onClick={handleNavAction}>
            {item.label}
          </Link>
        ),
      )}
    </nav>
  );
}
