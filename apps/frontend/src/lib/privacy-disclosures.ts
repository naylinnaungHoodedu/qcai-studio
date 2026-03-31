export const RETENTION_SCHEDULE = [
  {
    dataClass: "Guest continuity cookies",
    personalData: "Random guest identifier and CSRF token only.",
    retention: "365 days from issuance or refresh.",
    trigger: "Expires automatically or is replaced when the guest session is reset.",
  },
  {
    dataClass: "Guest-linked study activity",
    personalData: "Notes, quiz attempts, builder runs, project drafts, progress, and analytics tied to a guest ID.",
    retention: "Up to 365 days.",
    trigger: "Automatic retention cleanup removes stale guest records older than one year.",
  },
  {
    dataClass: "Local account sessions",
    personalData: "Session token hash, CSRF token, and expiry metadata.",
    retention: "30 days maximum or until logout.",
    trigger: "Logout, session expiry, or startup cleanup for expired sessions.",
  },
  {
    dataClass: "Local account and learner records",
    personalData: "Email, password hash, notes, quiz history, builder activity, projects, peer reviews, and learner profile data.",
    retention: "Until the user deletes the account or requests removal.",
    trigger: "Delete-account flow removes the local account and the linked learner records in the live app.",
  },
  {
    dataClass: "Public web-vitals telemetry",
    personalData: "Page path, metric name, metric value, connection type, and browser user-agent string.",
    retention: "30 days.",
    trigger: "Automatic retention cleanup removes older browser-performance samples.",
  },
  {
    dataClass: "Support requests",
    personalData: "Name, email address, organization, message, page URL, request type, and user-agent string.",
    retention: "540 days.",
    trigger: "Automatic retention cleanup removes older support records after the review/support window closes.",
  },
] as const;

export const COOKIE_INVENTORY = [
  {
    name: "qcai_guest_id",
    purpose: "Keeps a guest learner on the same study path across lessons, builder, dashboard, and project surfaces.",
    lifetime: "365 days",
    necessary: "Strictly necessary",
    setWhen: "Set when a visitor opens a guest-supported study surface that needs continuity.",
  },
  {
    name: "qcai_guest_csrf",
    purpose: "Protects guest-side mutations against cross-site request forgery.",
    lifetime: "365 days",
    necessary: "Strictly necessary",
    setWhen: "Set alongside the guest continuity cookie when guest mutation protection is needed.",
  },
  {
    name: "qcai_session_token",
    purpose: "Maintains a first-party local account session after sign-in.",
    lifetime: "30 days maximum",
    necessary: "Strictly necessary",
    setWhen: "Set only after a successful local-account registration or login.",
  },
  {
    name: "qcai_auth_csrf",
    purpose: "Protects authenticated account mutations such as logout and delete-account.",
    lifetime: "30 days maximum",
    necessary: "Strictly necessary",
    setWhen: "Set alongside the local-account session cookie after sign-in.",
  },
] as const;

export const PRIVACY_IMPLEMENTATION_NOTES = [
  "The current public deployment does not rely on advertising cookies or third-party marketing trackers to deliver lessons.",
  "If a future deployment enables optional federated identity or AI integrations, those providers may set their own provider-managed cookies only during the user-initiated flow that needs them.",
  "Provider-managed infrastructure logs are controlled at the hosting layer and are not individually configurable from this public web app surface.",
] as const;
