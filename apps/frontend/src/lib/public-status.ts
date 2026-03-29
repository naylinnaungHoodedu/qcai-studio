export const FEATURE_AVAILABILITY = [
  {
    title: "Curriculum and lesson reading",
    status: "Available now",
    detail:
      "Modules, lessons, syllabus, About, Attribution, and the new Simulations hub are public and fully reachable without sign-in.",
  },
  {
    title: "Grounded search and Q&A",
    status: "Available with fallback",
    detail:
      "Search and Q&A stay source-grounded in production. When OpenAI or Pinecone secrets are absent, the site falls back to grounded lexical retrieval instead of pretending semantic mode is active.",
  },
  {
    title: "Practice surfaces",
    status: "Guest mode",
    detail:
      "Dashboard, projects, builder, and arena are usable in a browser guest session. Cross-device continuity still depends on authenticated identity being configured on the deployment.",
  },
  {
    title: "Persistent identity",
    status: "Environment-gated",
    detail:
      "Auth0-backed sign-in is prepared in the codebase, but the public deployment currently prioritizes guest-first evaluation unless client-side Auth0 variables are exposed.",
  },
] as const;

export const RECENT_UPDATES = [
  {
    date: "March 29, 2026",
    title: "Published the Simulations hub",
    detail:
      "The site now includes a verified public simulations program with corrected concept notes, interaction rules, API-extension requirements, and a phased implementation roadmap.",
  },
  {
    date: "March 28, 2026",
    title: "Improved public curriculum trust surfaces",
    detail:
      "Modules, About, Attribution, Account, sitemap, metadata, and lesson navigation were tightened so visitors can evaluate the platform without hidden assumptions.",
  },
  {
    date: "March 28, 2026",
    title: "Fixed deployment and syllabus presentation issues",
    detail:
      "Manifest hygiene, transcript fallback labeling, guest-session documentation, and syllabus citation duplication were corrected and redeployed.",
  },
] as const;

export const EXPANSION_ROADMAP = [
  {
    title: "Expand beyond the seven-lesson studio track",
    detail:
      "The current course remains an intensive starter-to-project path. The next visible step is to grow it into a fuller 12-15 week curriculum with additional lessons and labs per module.",
  },
  {
    title: "Ship the first public simulation build",
    detail:
      "The verified roadmap already identifies SIM-01A, the NISQ Fidelity Cliff, as the fastest high-value public interactive build.",
  },
  {
    title: "Add completion signals learners can carry forward",
    detail:
      "The product already uses portfolio-style rubrics. The next step is a completion badge and exportable portfolio summary that can travel outside the platform.",
  },
  {
    title: "Harden public-experience operations",
    detail:
      "Mobile-specific UX testing, Lighthouse-based regression monitoring, and broader discoverability work remain active follow-up items rather than hidden backlog.",
  },
] as const;

export const COMPLETION_SIGNAL_NOTES = [
  "Current completion signal: rubric-backed project submissions and peer reviews tied to the public curriculum.",
  "Planned upgrade: completion badge and portfolio export so learners can carry evidence of work beyond the platform itself.",
] as const;
