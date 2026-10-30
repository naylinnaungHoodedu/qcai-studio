export const RETENTION_SCHEDULE = [
  {
    dataClass: "Guest continuity cookies",
    personalData: "Random guest identifier in a server-signed token, and a CSRF token derived from it.",
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
  {
    dataClass: "Rate-limit and sign-in lockout counters",
    personalData:
      "A keyed one-way digest of the account or guest ID, the network address or the sign-in email, with a request count. No raw ID, address or email is stored.",
    retention: "Until the counting window ends: at most one hour, or 15 minutes for a sign-in lockout.",
    trigger: "A counter restarts when its window ends, and automatic retention cleanup removes ended windows.",
  },
  {
    dataClass: "Security event log",
    personalData:
      "Sign-ins, sign-ups, account deletions, rejected credentials, blocked or rate-limited requests and administrator actions on guest sessions: the event, time, outcome and role, with keyed one-way digests of the account or guest ID and of the network address. No name, email address or raw ID is stored.",
    retention: "365 days.",
    trigger:
      "Automatic retention cleanup removes older events. Events cannot be edited or deleted sooner, including on account deletion; a deleted account's digest no longer matches any stored ID.",
  },
] as const;

export const COOKIE_INVENTORY = [
  {
    name: "qcai_guest_token",
    purpose: "Server-signed guest token that keeps a guest learner on the same study path across lessons, builder, dashboard, and project surfaces.",
    lifetime: "365 days",
    necessary: "Strictly necessary",
    setWhen: "Set when a visitor opens a guest-supported study surface that needs continuity.",
  },
  {
    name: "qcai_guest_csrf",
    purpose: "Protects guest-side mutations against cross-site request forgery; derived from, and only valid with, the guest token.",
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
  {
    name: "qcai_auth_token",
    purpose: "Holds the access token from the optional federated (Auth0) sign-in.",
    lifetime: "The token lifetime the identity provider returns (1 hour when it returns none)",
    necessary: "Strictly necessary",
    setWhen: "Set only after a completed federated sign-in; that sign-in is not enabled on the public deployment.",
  },
  {
    name: "qcai_auth_state",
    purpose: "Protects the federated sign-in redirect against forged responses.",
    lifetime: "10 minutes",
    necessary: "Strictly necessary",
    setWhen: "Set when a federated sign-in starts, and cleared when it completes.",
  },
  {
    name: "qcai_auth_verifier",
    purpose: "Holds the PKCE verifier for the federated sign-in.",
    lifetime: "10 minutes",
    necessary: "Strictly necessary",
    setWhen: "Set when a federated sign-in starts, and cleared when it completes.",
  },
  {
    name: "qcai_auth_return_to",
    purpose: "Remembers which page to return to after the federated sign-in.",
    lifetime: "10 minutes",
    necessary: "Strictly necessary",
    setWhen: "Set when a federated sign-in starts, and cleared when it completes.",
  },
  {
    name: "qcai_guest_id",
    purpose: "Legacy unsigned guest identifier, replaced by qcai_guest_token.",
    lifetime: "Deleted on the next visit",
    necessary: "Strictly necessary",
    setWhen: "No longer set; an existing one is deleted when the browser next opens a guest study surface.",
  },
] as const;

export const BROWSER_STORAGE_INVENTORY = [
  {
    key: "qcai-theme",
    purpose: "Remembers the light or dark theme choice.",
    storedWhere: "This browser's local storage",
    setWhen: "Set when the theme toggle is used.",
  },
  {
    key: "qcai-arena-player-id",
    purpose: "Random Arena player id this browser chose before the Arena used the session's identity.",
    storedWhere: "This browser's local storage",
    setWhen: "No longer set; an existing one is deleted when the Arena page next opens.",
  },
  {
    key: "qcai-arena-player-name",
    purpose: "The Arena handle typed into the Arena page.",
    storedWhere: "This browser's local storage",
    setWhen: "Set when an Arena handle is entered.",
  },
  {
    key: "qcai-learner-record-replica",
    purpose: "Device copy of the signed-in learner record, for offline continuity.",
    storedWhere: "This browser's local storage",
    setWhen: "Set only for a signed-in learner using the learner record.",
  },
  {
    key: "qcai-learner-record-clock",
    purpose: "Version clock that keeps the device copy of the learner record in step with the server.",
    storedWhere: "This browser's local storage",
    setWhen: "Set alongside the learner-record device copy.",
  },
] as const;

export const PRIVACY_IMPLEMENTATION_NOTES = [
  "The current public deployment does not rely on advertising cookies or third-party marketing trackers to deliver lessons.",
  "If a future deployment enables optional federated identity or AI integrations, those providers may set their own provider-managed cookies only during the user-initiated flow that needs them.",
  "Provider-managed infrastructure logs are controlled at the hosting layer and are not individually configurable from this public web app surface.",
] as const;
