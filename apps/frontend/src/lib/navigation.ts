export const PRACTICE_NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Arena", href: "/arena" },
  { label: "Builder", href: "/builder" },
] as const;

export const PRIMARY_NAV_ITEMS = [
  { label: "Overview", href: "/" },
  { label: "About", href: "/about" },
  { label: "Modules", href: "/modules" },
  { label: "Projects", href: "/projects" },
  { label: "Practice", children: PRACTICE_NAV_ITEMS },
  { label: "Simulations", href: "/simulations" },
  { label: "Account", href: "/account" },
  { label: "Search", href: "/search" },
] as const;
