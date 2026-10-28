"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { closeOpenNavGroups } from "@/lib/nav-disclosure";
import { PRIMARY_NAV_ITEMS } from "@/lib/navigation";

// A nav target is "active" when the current path is that page or lives under it,
// so learners always see where they are. Home ("/") only matches exactly.
function isActiveHref(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function PrimaryNav() {
  const pathname = usePathname();
  const shellRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const [openMenuPathname, setOpenMenuPathname] = useState<string | null>(null);
  const isMenuOpen = openMenuPathname === pathname;

  function handleNavAction() {
    setOpenMenuPathname(null);
    closeOpenNavGroups(navRef.current);
  }

  useEffect(() => {
    closeOpenNavGroups(navRef.current);
  }, [pathname]);

  useEffect(() => {
    if (!isMenuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      if (event.target instanceof Node && shellRef.current?.contains(event.target)) {
        return;
      }

      setOpenMenuPathname(null);
      closeOpenNavGroups(navRef.current);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }

      setOpenMenuPathname(null);
      closeOpenNavGroups(navRef.current);
    }

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isMenuOpen]);

  return (
    <div className="site-nav-shell" ref={shellRef}>
      <button
        aria-controls="primary-navigation-panel"
        aria-expanded={isMenuOpen}
        className="site-nav-toggle"
        onClick={() => setOpenMenuPathname((current) => (current === pathname ? null : pathname))}
        type="button"
      >
        <span>{isMenuOpen ? "Close menu" : "Menu"}</span>
        <span className="site-nav-toggle-icon" data-open={isMenuOpen ? "true" : "false"} aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </button>
      <nav
        aria-label="Primary"
        className={`site-nav ${isMenuOpen ? "is-open" : ""}`}
        id="primary-navigation-panel"
        ref={navRef}
      >
        {PRIMARY_NAV_ITEMS.map((item) =>
          "children" in item ? (
            <details className="site-nav-group" key={item.label}>
              <summary
                className={
                  item.children.some((child) => isActiveHref(pathname, child.href)) ? "is-active" : undefined
                }
              >
                {item.label}
              </summary>
              <div className="site-subnav" role="group" aria-label={`${item.label} links`}>
                {item.children.map((child) => {
                  const active = isActiveHref(pathname, child.href);
                  return (
                    <Link
                      aria-current={active ? "page" : undefined}
                      className={active ? "is-active" : undefined}
                      href={child.href}
                      key={child.href}
                      onClick={handleNavAction}
                    >
                      {child.label}
                    </Link>
                  );
                })}
              </div>
            </details>
          ) : (
            <Link
              aria-current={isActiveHref(pathname, item.href) ? "page" : undefined}
              className={isActiveHref(pathname, item.href) ? "is-active" : undefined}
              href={item.href}
              key={item.href}
              onClick={handleNavAction}
            >
              {item.label}
            </Link>
          ),
        )}
      </nav>
    </div>
  );
}
