// Practice groups the interactive "do something" surfaces behind one menu so the
// top-level bar stays short. Projects moved in here (was a separate top-level item).
export const PRACTICE_NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Arena", href: "/arena" },
  { label: "Builder", href: "/builder" },
  { label: "Projects", href: "/projects" },
] as const;

// Simplified primary navigation: 5 top-level targets instead of 8.
// - "Overview" removed: the brand mark (top-left) already links to the home page.
// - "About" removed from the bar: it remains reachable from the site footer.
// - "Projects" folded into the Practice menu.
// Modules and Simulations stay direct so the core learning path is one click.
export const PRIMARY_NAV_ITEMS = [
  { label: "Modules", href: "/modules" },
  { label: "Simulations", href: "/simulations" },
  { label: "Practice", children: PRACTICE_NAV_ITEMS },
  { label: "Search", href: "/search" },
  { label: "Account", href: "/account" },
] as const;
