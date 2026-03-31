export const SUPPORT_REQUEST_TYPES = [
  { value: "product", label: "Product support" },
  { value: "privacy", label: "Privacy request" },
  { value: "partnership", label: "Partnership or pilot" },
  { value: "security", label: "Security disclosure" },
] as const;

export const SUPPORT_RESPONSE_TARGETS = [
  {
    title: "Product and privacy",
    target: "First response within 2 business days",
    detail: "Covers learner help, account issues, privacy questions, and correction/deletion follow-up.",
  },
  {
    title: "Partnership and pilots",
    target: "First response within 5 business days",
    detail: "Used for evaluative reviews, institutional pilots, and manually scoped commercial conversations.",
  },
  {
    title: "Security disclosures",
    target: "Acknowledgement within 5 business days",
    detail: "Initial acknowledgement arrives through the public disclosure channel before any deeper remediation timeline is confirmed.",
  },
] as const;

export const STATUS_CHANNELS = [
  {
    title: "Public support intake",
    status: "Live",
    detail: "The support page now includes a structured intake form that records requests and returns a public ticket reference.",
  },
  {
    title: "Operational status surface",
    status: "Live",
    detail: "The status page summarizes live API health, response expectations, recent releases, and current hardening decisions.",
  },
  {
    title: "Browser telemetry",
    status: "Live",
    detail: "Core Web Vitals are reported from the browser to a first-party endpoint and summarized for public monitoring.",
  },
] as const;

export const ACCESSIBILITY_VALIDATION_LOG = [
  {
    flow: "Builder workbench",
    status: "Validated",
    detail:
      "Keyboard traversal, slot activation, removal, focus visibility, and live-status messaging were rechecked on the public builder flow.",
  },
  {
    flow: "Account lifecycle",
    status: "Validated",
    detail:
      "Create, login, logout, and delete-account forms were rechecked for labels, visible focus, and clear submission messaging.",
  },
  {
    flow: "Lesson playback and study controls",
    status: "Validated",
    detail:
      "Lesson navigation, flashcard/quiz links, media framing, and public study actions were reviewed for structural semantics and keyboard reachability.",
  },
  {
    flow: "Automated accessibility tooling",
    status: "Live",
    detail:
      "A browser-based Lighthouse accessibility audit now runs against the public route set through npm test:a11y.",
  },
] as const;

export const ACCESSIBILITY_FIX_LOG = [
  {
    title: "Builder step targets remain keyboard reachable",
    detail:
      "Circuit slots keep focus, announce their placement status, and support Enter, Space, Delete, and Backspace interactions.",
  },
  {
    title: "Support intake uses labeled controls and status messaging",
    detail:
      "Each support field is labeled, validation text is explicit, and submission results are announced in a live region.",
  },
  {
    title: "Public ops pages keep a predictable document structure",
    detail:
      "Status and accessibility pages follow the site-wide skip-link, heading, landmark, and panel patterns.",
  },
] as const;

export const ACCESSIBILITY_TRACKED_FOLLOWUPS = [
  "A full NVDA/VoiceOver assistive-technology lab pass remains an explicit operational follow-up because it requires dedicated screen-reader environments outside the deployment pipeline.",
  "Simulation-heavy interactions should continue to be rechecked when new drag, chart, or canvas behaviors are added.",
] as const;

export const PERFORMANCE_THRESHOLDS = [
  { page: "/", performance: 0.8, accessibility: 0.95, bestPractices: 0.9, seo: 0.9 },
  { page: "/modules", performance: 0.8, accessibility: 0.95, bestPractices: 0.9, seo: 0.9 },
  { page: "/lessons/nisq-reality-overview", performance: 0.75, accessibility: 0.95, bestPractices: 0.9, seo: null },
  { page: "/builder", performance: 0.7, accessibility: 0.95, bestPractices: 0.9, seo: null },
  { page: "/account", performance: 0.8, accessibility: 0.95, bestPractices: 0.9, seo: null },
  { page: "/support", performance: 0.8, accessibility: 0.95, bestPractices: 0.9, seo: 0.9 },
] as const;

export const SECURITY_HARDENING_DECISIONS = [
  {
    title: "CSP style-attribute hardening is still in progress",
    detail:
      "The live CSP no longer allows broad inline styles, but style-src-attr remains temporarily enabled because builder and simulation surfaces still rely on inline positioning, sizing, and accent variables.",
  },
  {
    title: "COEP is intentionally deferred",
    detail:
      "Cross-Origin-Embedder-Policy is not enabled yet because the public deployment still needs a broader compatibility review across protected media delivery, future embeds, and any cross-origin learning integrations.",
  },
] as const;
