export const AUDIT_ROLE_CLUSTERS = [
  "guest",
  "learner",
  "instructor_creator",
  "admin_support",
  "manager_guardian",
] as const;

export const AUDIT_JOURNEY_CATEGORIES = [
  "onboarding_authentication",
  "course_discovery_enrollment_purchase",
  "learning_experience",
  "content_creation_moderation",
  "support_operations",
  "data_rights_privacy",
  "notifications_preferences",
  "error_paths",
] as const;

export const AUDIT_FOCUS_AREAS = [
  "ux",
  "security",
  "privacy",
  "accessibility",
  "performance",
  "reliability",
  "billing",
  "moderation_governance",
  "trust",
  "data_integrity",
] as const;

export type AuditRoleCluster = (typeof AUDIT_ROLE_CLUSTERS)[number];
export type AuditJourneyCategory = (typeof AUDIT_JOURNEY_CATEGORIES)[number];
export type AuditFocusArea = (typeof AUDIT_FOCUS_AREAS)[number];

export type AuditUserAccount = {
  id: string;
  personaName: string;
  role: string;
  roleCluster: AuditRoleCluster;
  goals: readonly string[];
  primaryDevice: string;
  connectivity: string;
  locale: string;
  timezone: string;
  languagePreference: string;
  accessibilityNeeds: readonly string[];
  accountStatus: string;
  entitlements: readonly string[];
  enrollments: readonly string[];
  userId: string;
  email: string | null;
  phone: string | null;
  orgId: string | null;
  riskFlags: readonly string[];
};

export type AuditUserCommand = {
  id: string;
  roleCluster: "learner" | "instructor_creator" | "admin_support" | "manager_guardian";
  accountIds: readonly string[];
  categories: readonly AuditJourneyCategory[];
  commandText: string;
  preconditions: readonly string[];
  expectedOutcome: readonly string[];
  negativeVariant: string;
  auditFocus: readonly AuditFocusArea[];
};

export const AUDIT_USER_ACCOUNTS: readonly AuditUserAccount[] = [
  {
    id: "AC-01",
    personaName: "Tess Drift",
    role: "Guest prospect",
    roleCluster: "guest",
    goals: [
      "Preview a lesson and compare the curriculum before creating an account.",
      "Understand what is public, what requires signup, and what data is stored in a guest session.",
    ],
    primaryDevice: "Shared Windows laptop",
    connectivity: "Public Wi-Fi",
    locale: "en-US",
    timezone: "America/Denver",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "anonymous_session",
    entitlements: ["public-preview"],
    enrollments: [],
    userId: "guest_ql_001",
    email: null,
    phone: null,
    orgId: null,
    riskFlags: ["shared-device", "cookie-choice-sensitive"],
  },
  {
    id: "AC-02",
    personaName: "Mira Fen",
    role: "Learner, new",
    roleCluster: "learner",
    goals: [
      "Create a first account from mobile and verify the email flow without confusion.",
      "Enroll in an introductory module quickly after signup.",
    ],
    primaryDevice: "Android phone",
    connectivity: "Intermittent 4G",
    locale: "en-US",
    timezone: "America/Chicago",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "unverified",
    entitlements: ["free"],
    enrollments: ["QC+AI Overview and the NISQ Reality"],
    userId: "usr_ql_002",
    email: "mira.fen@ql.test",
    phone: "+1-555-010-1002",
    orgId: null,
    riskFlags: ["first-login-friction"],
  },
  {
    id: "AC-03",
    personaName: "Oren Clave",
    role: "Learner, returning paid pilot",
    roleCluster: "learner",
    goals: [
      "Resume lessons across desktop and tablet without losing progress.",
      "Keep receipts, certificates, and billing records consistent across renewals.",
    ],
    primaryDevice: "MacBook Air",
    connectivity: "Home broadband",
    locale: "en-US",
    timezone: "America/Los_Angeles",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "active",
    entitlements: ["paid-pilot"],
    enrollments: [
      "QC+AI Overview and the NISQ Reality",
      "Intermediate Quantum Programming",
      "Advanced Quantum Software Development",
    ],
    userId: "usr_ql_003",
    email: "oren.clave@ql.test",
    phone: "+1-555-010-1003",
    orgId: null,
    riskFlags: ["unsubscribed-marketing"],
  },
  {
    id: "AC-04",
    personaName: "Sana Iver",
    role: "Learner, scholarship",
    roleCluster: "learner",
    goals: [
      "Use scholarship-funded access without billing friction.",
      "Complete a practical learning path tied to career transition goals.",
    ],
    primaryDevice: "Chromebook",
    connectivity: "School Wi-Fi",
    locale: "en-GB",
    timezone: "Europe/London",
    languagePreference: "English",
    accessibilityNeeds: ["captions-preferred"],
    accountStatus: "active",
    entitlements: ["scholarship"],
    enrollments: ["Hardware-Constrained QC+AI Models", "Quantum Finance Programming and Optimization"],
    userId: "usr_ql_004",
    email: "sana.iver@ql.test",
    phone: "+1-555-010-1004",
    orgId: null,
    riskFlags: ["financial-aid-sensitive"],
  },
  {
    id: "AC-05",
    personaName: "Jae Tolland",
    role: "Learner, low bandwidth",
    roleCluster: "learner",
    goals: [
      "Stream lessons on a weak mobile connection and save files for offline reading.",
      "Finish checkpoints during a commute without repeated session loss.",
    ],
    primaryDevice: "Low-end Android phone",
    connectivity: "Unstable 3G",
    locale: "en-US",
    timezone: "America/New_York",
    languagePreference: "English",
    accessibilityNeeds: ["reduced-motion-preferred"],
    accountStatus: "active",
    entitlements: ["free"],
    enrollments: ["Introduction to Hardware-Constrained Learning"],
    userId: "usr_ql_005",
    email: "jae.tolland@ql.test",
    phone: "+1-555-010-1005",
    orgId: null,
    riskFlags: ["low-bandwidth"],
  },
  {
    id: "AC-06",
    personaName: "Ari Solen",
    role: "Learner, accessibility-critical",
    roleCluster: "learner",
    goals: [
      "Complete lessons and quizzes using keyboard and screen reader only.",
      "Confirm that captions, transcripts, and focus management hold across dynamic flows.",
    ],
    primaryDevice: "Windows laptop",
    connectivity: "Broadband",
    locale: "en-US",
    timezone: "America/Phoenix",
    languagePreference: "English",
    accessibilityNeeds: ["screen-reader", "keyboard-only", "high-contrast", "captions-required"],
    accountStatus: "active",
    entitlements: ["paid-pilot"],
    enrollments: ["Intermediate Quantum Programming", "QC+AI Builder Practice"],
    userId: "usr_ql_006",
    email: "ari.solen@ql.test",
    phone: "+1-555-010-1006",
    orgId: null,
    riskFlags: ["accessibility-critical"],
  },
  {
    id: "AC-07",
    personaName: "Tomas Quill",
    role: "Learner, renewal failed",
    roleCluster: "learner",
    goals: [
      "Recover access after a payment failure without losing progress.",
      "Understand the grace period and invoice status clearly.",
    ],
    primaryDevice: "iPad",
    connectivity: "Home Wi-Fi",
    locale: "en-US",
    timezone: "America/Seattle",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "grace-period",
    entitlements: ["paid-pilot-renewal-failed"],
    enrollments: ["Quantum Finance Programming and Optimization"],
    userId: "usr_ql_007",
    email: "tomas.quill@ql.test",
    phone: "+1-555-010-1007",
    orgId: null,
    riskFlags: ["payment-retry-open"],
  },
  {
    id: "AC-08",
    personaName: "Lina Voss",
    role: "Learner, privacy-sensitive",
    roleCluster: "learner",
    goals: [
      "Export learning data and understand exactly what is retained.",
      "Use the product in English while living under GDPR-sensitive expectations.",
    ],
    primaryDevice: "Linux laptop",
    connectivity: "Fiber broadband",
    locale: "de-DE",
    timezone: "Europe/Berlin",
    languagePreference: "German and English",
    accessibilityNeeds: [],
    accountStatus: "active",
    entitlements: ["paid-pilot"],
    enrollments: ["QC+AI Overview and the NISQ Reality"],
    userId: "usr_ql_008",
    email: "lina.voss@ql.test",
    phone: "+1-555-010-1008",
    orgId: null,
    riskFlags: ["gdpr-request-open", "pii-sensitive"],
  },
  {
    id: "AC-09",
    personaName: "Noa Kest",
    role: "Learner, minor",
    roleCluster: "learner",
    goals: [
      "Start only after guardian approval is recorded.",
      "Use age-appropriate communication settings and restricted community access.",
    ],
    primaryDevice: "School iPad",
    connectivity: "Managed school Wi-Fi",
    locale: "en-US",
    timezone: "America/Denver",
    languagePreference: "English",
    accessibilityNeeds: ["dyslexia-friendly-spacing-preferred"],
    accountStatus: "pending-consent",
    entitlements: ["minor-trial"],
    enrollments: ["QC+AI Overview and the NISQ Reality"],
    userId: "usr_ql_009",
    email: "noa.kest@ql.test",
    phone: "+1-555-010-1009",
    orgId: null,
    riskFlags: ["minor-flagged", "consent-required"],
  },
  {
    id: "AC-10",
    personaName: "Rin Halden",
    role: "Learner, locked after suspicious login",
    roleCluster: "learner",
    goals: [
      "Regain access safely after a suspicious-login alert.",
      "Verify that stale sessions can be revoked without losing course work.",
    ],
    primaryDevice: "Windows desktop",
    connectivity: "Broadband",
    locale: "en-US",
    timezone: "America/Atlanta",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "locked",
    entitlements: ["paid-pilot"],
    enrollments: ["Advanced Quantum Software Development"],
    userId: "usr_ql_010",
    email: "rin.halden@ql.test",
    phone: "+1-555-010-1010",
    orgId: null,
    riskFlags: ["suspicious-login", "risk-review"],
  },
  {
    id: "AC-11",
    personaName: "Pax Merrin",
    role: "Learner, duplicate-email edge case",
    roleCluster: "learner",
    goals: [
      "Resolve a duplicate-email or alias conflict without creating a second identity.",
      "Keep notification preferences and deletion choices intact after account cleanup.",
    ],
    primaryDevice: "Android phone",
    connectivity: "LTE",
    locale: "en-US",
    timezone: "America/Toronto",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "active-with-merge-review",
    entitlements: ["trial-expired"],
    enrollments: [],
    userId: "usr_ql_011",
    email: "pax.merrin@ql.test",
    phone: "+1-555-010-1011",
    orgId: null,
    riskFlags: ["duplicate-email-review", "ccpa-delete-interest", "unsubscribed-marketing"],
  },
  {
    id: "AC-12",
    personaName: "Nia Calder",
    role: "Instructor and course creator",
    roleCluster: "instructor_creator",
    goals: [
      "Publish an accessible cohort course with clear prerequisites and pricing metadata.",
      "Monitor learner progress using privacy-safe analytics.",
    ],
    primaryDevice: "MacBook Pro",
    connectivity: "Broadband",
    locale: "en-US",
    timezone: "America/Chicago",
    languagePreference: "English",
    accessibilityNeeds: ["captions-required-for-all-uploads"],
    accountStatus: "active",
    entitlements: ["creator-pro"],
    enrollments: ["Author of Team Skills Studio"],
    userId: "usr_ql_012",
    email: "nia.calder@ql.test",
    phone: "+1-555-010-1012",
    orgId: null,
    riskFlags: ["content-publisher"],
  },
  {
    id: "AC-13",
    personaName: "Pavel Sorrel",
    role: "Instructor under moderation review",
    roleCluster: "instructor_creator",
    goals: [
      "Revise flagged content and resolve policy or IP concerns fairly.",
      "Retain audit history of revisions and takedown decisions.",
    ],
    primaryDevice: "Windows laptop",
    connectivity: "Broadband",
    locale: "en-GB",
    timezone: "Europe/Dublin",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "review-hold",
    entitlements: ["creator-trial"],
    enrollments: ["Author of Responsible AI Writing Lab"],
    userId: "usr_ql_013",
    email: "pavel.sorrel@ql.test",
    phone: "+1-555-010-1013",
    orgId: null,
    riskFlags: ["moderation-review"],
  },
  {
    id: "AC-14",
    personaName: "Daria Flint",
    role: "Support agent",
    roleCluster: "admin_support",
    goals: [
      "Resolve billing, auth, and privacy tickets with least-privilege access.",
      "Leave a clean, auditable trail for every user-visible action.",
    ],
    primaryDevice: "Managed Windows workstation",
    connectivity: "Office network",
    locale: "en-US",
    timezone: "America/New_York",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "active-staff",
    entitlements: ["support-console"],
    enrollments: [],
    userId: "usr_ql_014",
    email: "daria.flint@ql.test",
    phone: "+1-555-010-1014",
    orgId: "org_staff_support",
    riskFlags: ["privileged-staff"],
  },
  {
    id: "AC-15",
    personaName: "Ivo Mercer",
    role: "Trust and safety admin",
    roleCluster: "admin_support",
    goals: [
      "Handle moderation, ban appeals, and security disclosures with clear escalation paths.",
      "Avoid overbroad actions and preserve evidence for review.",
    ],
    primaryDevice: "Managed MacBook",
    connectivity: "Office VPN",
    locale: "en-US",
    timezone: "America/Los_Angeles",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "active-staff",
    entitlements: ["trust-safety-console"],
    enrollments: [],
    userId: "usr_ql_015",
    email: "ivo.mercer@ql.test",
    phone: "+1-555-010-1015",
    orgId: "org_staff_trust",
    riskFlags: ["high-privilege"],
  },
  {
    id: "AC-16",
    personaName: "Corin Vale",
    role: "Enterprise and team manager",
    roleCluster: "manager_guardian",
    goals: [
      "Roll out a controlled team learning program with SSO, seat governance, and privacy-safe reporting.",
      "Understand billing, procurement, and support commitments before expanding usage.",
    ],
    primaryDevice: "Corporate ThinkPad",
    connectivity: "Office broadband",
    locale: "en-US",
    timezone: "America/Denver",
    languagePreference: "English",
    accessibilityNeeds: [],
    accountStatus: "active",
    entitlements: ["enterprise-admin"],
    enrollments: ["Enterprise learning path owner"],
    userId: "usr_ql_016",
    email: "corin.vale@ql.test",
    phone: "+1-555-010-1016",
    orgId: "org_ql_016",
    riskFlags: ["org-admin", "invoice-sensitive"],
  },
  {
    id: "AC-17",
    personaName: "Hela Kest",
    role: "Parent and guardian",
    roleCluster: "manager_guardian",
    goals: [
      "Grant and revoke consent for a linked minor learner without ambiguity.",
      "Monitor progress and privacy choices for the linked child account only.",
    ],
    primaryDevice: "iPhone",
    connectivity: "Home Wi-Fi",
    locale: "en-US",
    timezone: "America/Denver",
    languagePreference: "English",
    accessibilityNeeds: ["large-text-preferred"],
    accountStatus: "active-guardian",
    entitlements: ["guardian-portal"],
    enrollments: ["Linked to AC-09 only"],
    userId: "usr_ql_017",
    email: "hela.kest@ql.test",
    phone: "+1-555-010-1017",
    orgId: null,
    riskFlags: ["consent-authority", "pii-sensitive"],
  },
] as const;

export const AUDIT_USER_COMMANDS: readonly AuditUserCommand[] = [
  {
    id: "L-01",
    roleCluster: "learner",
    accountIds: ["AC-01", "AC-02"],
    categories: ["onboarding_authentication", "course_discovery_enrollment_purchase"],
    commandText:
      "As a guest, I want to preview Module 1, save it for later, and then create an account without losing the preview trail.",
    preconditions: [
      "Guest preview is enabled for at least one lesson or module card.",
      "A guest session can store a lightweight wishlist or recently viewed item.",
    ],
    expectedOutcome: [
      "Public content stays public and gated content stays gated.",
      "The signup flow explains whether guest state will migrate or reset.",
      "After account creation, the saved module context is preserved or clearly disclosed as non-portable.",
    ],
    negativeVariant:
      "Guest cookies are blocked or expired, so the user is told exactly what will not carry over instead of silently losing state.",
    auditFocus: ["ux", "privacy", "security"],
  },
  {
    id: "L-02",
    roleCluster: "learner",
    accountIds: ["AC-02"],
    categories: ["onboarding_authentication", "error_paths"],
    commandText: "I want to sign up on my phone, verify my email, and retry safely if the first link expires.",
    preconditions: [
      "Email signup is enabled in the test environment.",
      "Verification emails are captured in a test mailbox or sink.",
    ],
    expectedOutcome: [
      "The account is created in an unverified state with clear next-step guidance.",
      "The first valid verification link succeeds and activates the account.",
      "A resend flow exists and does not create duplicate accounts.",
    ],
    negativeVariant:
      "The user taps an expired or already-used link and gets a safe resend path instead of a generic failure page.",
    auditFocus: ["ux", "security", "reliability"],
  },
  {
    id: "L-03",
    roleCluster: "learner",
    accountIds: ["AC-03"],
    categories: ["onboarding_authentication", "error_paths"],
    commandText:
      "I want to sign in from a new laptop, review the new-device warning, and turn on MFA for future logins.",
    preconditions: [
      "The account is active and has at least one prior device or session on record.",
      "MFA enrollment is available in the test environment if the product supports it.",
    ],
    expectedOutcome: [
      "The login flow succeeds only after the required step-up checks complete.",
      "The new-device event is visible in account security history or notification copy.",
      "MFA setup is confirmed without locking the user out of the current session.",
    ],
    negativeVariant:
      "Repeated bad codes or passwords trigger rate-limited messaging without leaking whether the account exists.",
    auditFocus: ["security", "ux"],
  },
  {
    id: "L-04",
    roleCluster: "learner",
    accountIds: ["AC-03", "AC-10"],
    categories: ["onboarding_authentication", "support_operations", "error_paths"],
    commandText:
      "I forgot my password, my first reset link expired, and I still need a safe recovery path without bypassing identity checks.",
    preconditions: [
      "Password reset is enabled and sends a one-time or short-lived link.",
      "Support-assisted recovery exists or is intentionally unavailable with clear policy text.",
    ],
    expectedOutcome: [
      "The expired link is rejected cleanly.",
      "A new reset can be requested without creating multiple conflicting recovery states.",
      "If mailbox access is unavailable, the product routes the user to the documented recovery channel.",
    ],
    negativeVariant:
      "The user clicks a stale reset link from another device and the system must fail closed without confusing cross-session behavior.",
    auditFocus: ["security", "ux", "reliability"],
  },
  {
    id: "L-05",
    roleCluster: "learner",
    accountIds: ["AC-03", "AC-04"],
    categories: ["course_discovery_enrollment_purchase", "support_operations"],
    commandText:
      "I want to compare plan details, apply a scholarship or pilot discount, and enroll in Intermediate Quantum Programming.",
    preconditions: [
      "The environment exposes either self-serve billing or a partner-scoped price simulation.",
      "At least one valid and one invalid discount or scholarship code are configured.",
    ],
    expectedOutcome: [
      "Price, discount, entitlement scope, and any refund or billing note are visible before confirmation.",
      "The enrollment result matches the selected plan or scholarship state.",
      "A receipt, invoice, or enrollment confirmation is generated if applicable.",
    ],
    negativeVariant:
      "An expired or invalid code does not apply silently and does not alter the final entitlement unexpectedly.",
    auditFocus: ["ux", "billing", "trust"],
  },
  {
    id: "L-06",
    roleCluster: "learner",
    accountIds: ["AC-07"],
    categories: ["course_discovery_enrollment_purchase", "support_operations", "error_paths"],
    commandText:
      "My renewal failed. I want to update payment details, understand the grace period, and keep my course progress.",
    preconditions: [
      "The account is in a renewal-failed or grace-period state.",
      "The billing UI or support handoff exposes the next required action.",
    ],
    expectedOutcome: [
      "The user sees the renewal status, due amount, and access window clearly.",
      "Updating the payment method or invoice route restores access without erasing progress.",
      "Support or policy links explain what happens if payment is not recovered.",
    ],
    negativeVariant:
      "A second payment failure must not double-charge the user or silently strip access without an explanation.",
    auditFocus: ["billing", "ux", "reliability"],
  },
  {
    id: "L-07",
    roleCluster: "learner",
    accountIds: ["AC-05"],
    categories: ["learning_experience", "error_paths"],
    commandText:
      "I want to stream a lesson on a weak mobile connection, switch to a lighter mode, and save the document for offline reading.",
    preconditions: [
      "At least one lesson includes video plus a downloadable source asset.",
      "The media player or asset list exposes quality or retry behavior where supported.",
    ],
    expectedOutcome: [
      "Playback degrades gracefully or offers a fallback instead of freezing.",
      "Downloadable assets are labeled clearly for offline reading.",
      "The user can resume the lesson later without losing place unnecessarily.",
    ],
    negativeVariant:
      "A stalled network request surfaces a retry state or fallback asset instead of leaving the user on a dead loading spinner.",
    auditFocus: ["performance", "ux", "reliability", "accessibility"],
  },
  {
    id: "L-08",
    roleCluster: "learner",
    accountIds: ["AC-06"],
    categories: ["learning_experience", "error_paths"],
    commandText:
      "I want to complete a timed quiz using keyboard navigation, a screen reader, and clear focus states on every control.",
    preconditions: [
      "A quiz flow exists with keyboard-reachable controls.",
      "The environment supports screen reader and high-contrast checks.",
    ],
    expectedOutcome: [
      "Focus order is predictable and all quiz controls are labeled.",
      "Timer messaging, submission status, and validation errors are announced clearly.",
      "Autosave or recovery behavior preserves answers if the page refreshes.",
    ],
    negativeVariant:
      "Any focus trap, missing label, or inaccessible validation message is logged as a blocker instead of treated as cosmetic.",
    auditFocus: ["accessibility", "ux", "reliability"],
  },
  {
    id: "L-09",
    roleCluster: "learner",
    accountIds: ["AC-03", "AC-04"],
    categories: ["learning_experience", "notifications_preferences"],
    commandText:
      "After completing a module, I want the certificate, completion status, and any receipt or confirmation email to stay consistent.",
    preconditions: [
      "A course or module completion threshold is configured.",
      "Certificate issuance or completion badge logic is available in the test environment.",
    ],
    expectedOutcome: [
      "Completion status matches the recorded progress.",
      "The certificate or badge uses the correct learner identity and completion date.",
      "Any follow-up notifications match the actual completion event.",
    ],
    negativeVariant:
      "A recalculated quiz score or late sync must not revoke a certificate silently or produce a mismatched completion record.",
    auditFocus: ["ux", "reliability", "trust"],
  },
  {
    id: "L-10",
    roleCluster: "learner",
    accountIds: ["AC-03", "AC-11"],
    categories: ["notifications_preferences", "data_rights_privacy"],
    commandText:
      "I want marketing emails off, course reminders on, and cookie choices to be respected across devices.",
    preconditions: [
      "The product distinguishes marketing from transactional or learning-critical notifications.",
      "Cookie or analytics preferences are exposed if the product supports them.",
    ],
    expectedOutcome: [
      "Granular preference settings persist after refresh and re-login.",
      "Critical transactional notices remain appropriately scoped.",
      "Preference screens explain what cannot be turned off and why.",
    ],
    negativeVariant:
      "Unsubscribing from marketing must not disable password-reset, billing, or security notifications unintentionally.",
    auditFocus: ["privacy", "ux"],
  },
  {
    id: "L-11",
    roleCluster: "learner",
    accountIds: ["AC-08", "AC-11"],
    categories: ["data_rights_privacy", "support_operations"],
    commandText:
      "I want to export all of my learning data, support history, and receipts, then request account deletion with a retention explanation.",
    preconditions: [
      "Authenticated privacy-rights actions are available or routed to support.",
      "The account has enough history to validate export completeness.",
    ],
    expectedOutcome: [
      "The export includes the documented data categories for the user only.",
      "Deletion explains what is removed immediately and what is retained by policy.",
      "Active sessions are revoked after deletion is confirmed.",
    ],
    negativeVariant:
      "The export omits a major data class or the deletion flow fails without telling the user what happened next.",
    auditFocus: ["privacy", "security", "trust"],
  },
  {
    id: "L-12",
    roleCluster: "learner",
    accountIds: ["AC-10"],
    categories: ["onboarding_authentication", "error_paths"],
    commandText:
      "I received a suspicious-login warning. I want to review active sessions, sign out other devices, and recover the account safely.",
    preconditions: [
      "The account is locked or flagged after a suspicious event.",
      "Session-management or forced re-authentication controls are available.",
    ],
    expectedOutcome: [
      "The warning explains what triggered the lock or review state at a high level.",
      "Current and prior sessions can be reviewed or revoked safely.",
      "The account returns to a known-good state after recovery.",
    ],
    negativeVariant:
      "Stale sessions survive the recovery flow or the user cannot tell whether the account is safe again.",
    auditFocus: ["security", "ux", "reliability"],
  },
  {
    id: "I-01",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["onboarding_authentication", "content_creation_moderation"],
    commandText:
      "I want to activate a creator account, accept the content policy, and verify that I can publish only after the required checks are complete.",
    preconditions: [
      "Creator enrollment or role elevation is enabled in the test environment.",
      "Content policy acceptance is required before publish rights are granted.",
    ],
    expectedOutcome: [
      "The creator role is inactive until required steps are completed.",
      "Policy acceptance is timestamped and visible in the creator record.",
      "The UI distinguishes draft rights from publish rights clearly.",
    ],
    negativeVariant:
      "A partially configured creator should not be able to publish or expose incomplete public metadata.",
    auditFocus: ["security", "ux", "moderation_governance"],
  },
  {
    id: "I-02",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["content_creation_moderation"],
    commandText:
      "I want to draft a new course with a title, syllabus, prerequisites, outcomes, and pilot pricing notes.",
    preconditions: [
      "Draft authoring is enabled.",
      "The course model supports required metadata and validation.",
    ],
    expectedOutcome: [
      "Draft save works without data loss.",
      "Missing required metadata is called out before publish.",
      "The preview reflects the latest saved version.",
    ],
    negativeVariant:
      "A required field such as prerequisites or entitlement scope must not fail silently during save or publish.",
    auditFocus: ["ux", "reliability"],
  },
  {
    id: "I-03",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12", "AC-13"],
    categories: ["content_creation_moderation", "error_paths"],
    commandText:
      "I want to upload large videos and documents even if my connection drops midway through the upload.",
    preconditions: [
      "Large media or document upload is enabled.",
      "At least one large file is available in the test environment.",
    ],
    expectedOutcome: [
      "The upload flow resumes or retries without creating duplicate assets.",
      "The creator can tell which version is current.",
      "Partial or failed uploads do not become publicly visible.",
    ],
    negativeVariant:
      "A dropped connection leaves an orphaned asset, duplicate attachment, or inconsistent file-type state.",
    auditFocus: ["reliability", "performance", "ux"],
  },
  {
    id: "I-04",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["content_creation_moderation", "learning_experience"],
    commandText:
      "Before I publish, I want to add captions, transcripts, alt text, and download labels for every learner-facing asset.",
    preconditions: [
      "The course includes at least one video, one document, and one image or card-style visual.",
      "Accessibility metadata fields are exposed in authoring.",
    ],
    expectedOutcome: [
      "Accessibility fields are clearly attached to the relevant asset.",
      "Publish warnings appear if required metadata is missing.",
      "Learner views render the metadata correctly.",
    ],
    negativeVariant:
      "A creator can publish inaccessible media with no warning or cannot tell which assets still lack accessibility metadata.",
    auditFocus: ["accessibility", "ux", "trust"],
  },
  {
    id: "I-05",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["content_creation_moderation", "notifications_preferences"],
    commandText:
      "I want to schedule a course release for 09:00 in the learner-facing timezone and receive a confirmation digest.",
    preconditions: [
      "Scheduled publishing is enabled.",
      "Course and account timezone settings are configurable.",
    ],
    expectedOutcome: [
      "The schedule reflects an explicit timezone and release time.",
      "Notifications or status indicators confirm when the release occurred.",
      "Learner-facing availability matches the configured schedule.",
    ],
    negativeVariant:
      "Daylight-saving or timezone mismatches cause content to publish early or late with no visible warning.",
    auditFocus: ["ux", "reliability"],
  },
  {
    id: "I-06",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["content_creation_moderation", "learning_experience"],
    commandText:
      "I need to revise a published lesson without resetting learner progress, breaking bookmarks, or invalidating certificates.",
    preconditions: [
      "A published lesson already has active learners and recorded progress.",
      "Versioning or republish behavior is available.",
    ],
    expectedOutcome: [
      "Learner progress is preserved or changes are explained explicitly.",
      "Existing lesson links continue to resolve where intended.",
      "A version or change log is recorded for auditability.",
    ],
    negativeVariant:
      "Republishing unexpectedly restarts lessons, invalidates quiz attempts, or changes public slugs without redirection.",
    auditFocus: ["reliability", "ux", "trust"],
  },
  {
    id: "I-07",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12", "AC-06"],
    categories: ["content_creation_moderation", "learning_experience"],
    commandText:
      "I want to create a quiz with multiple attempts, time extensions, and explicit accommodations for accessibility-sensitive learners.",
    preconditions: [
      "Quiz authoring supports attempts, due dates, and accommodation overrides.",
      "At least one learner profile can receive an accommodation rule in the test environment.",
    ],
    expectedOutcome: [
      "The quiz rules are visible and saved correctly.",
      "The accommodation applies only to the intended learner or cohort.",
      "Learner-facing timing, messaging, and submission states stay consistent.",
    ],
    negativeVariant:
      "Accommodation settings leak to unintended learners or are ignored for the targeted learner at runtime.",
    auditFocus: ["accessibility", "ux", "reliability"],
  },
  {
    id: "I-08",
    roleCluster: "instructor_creator",
    accountIds: ["AC-13"],
    categories: ["content_creation_moderation", "support_operations"],
    commandText:
      "A submission or lesson was flagged for plagiarism or AI-policy issues. I want to review the evidence and decide fairly.",
    preconditions: [
      "An integrity or policy flag exists on a learner submission or creator asset.",
      "The relevant content policy is visible to the reviewer.",
    ],
    expectedOutcome: [
      "Evidence, policy basis, and next actions are visible in one workflow.",
      "The decision is logged and reversible through a documented appeal path.",
      "Affected users receive a clear explanation without exposing internal-only notes.",
    ],
    negativeVariant:
      "A false positive leaves the creator or learner with no context, no appeal path, or no retained evidence.",
    auditFocus: ["moderation_governance", "ux", "trust"],
  },
  {
    id: "I-09",
    roleCluster: "instructor_creator",
    accountIds: ["AC-13"],
    categories: ["content_creation_moderation", "support_operations"],
    commandText:
      "I need to unpublish or takedown a lesson after an intellectual-property or policy complaint while preserving audit history.",
    preconditions: [
      "A published asset is under complaint or review.",
      "The creator has access to a takedown workflow or moderation handoff.",
    ],
    expectedOutcome: [
      "The takedown action is logged with reason and timestamp.",
      "Learners see an appropriate replacement or explanation if access changes.",
      "Appeal or review status is visible to the creator.",
    ],
    negativeVariant:
      "The lesson disappears abruptly with no trace, no communication, or no way to distinguish temporary hold from permanent removal.",
    auditFocus: ["moderation_governance", "trust", "reliability"],
  },
  {
    id: "I-10",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["notifications_preferences", "data_rights_privacy"],
    commandText:
      "I want weekly creator analytics and course digests that help me improve teaching without exposing unnecessary learner PII.",
    preconditions: [
      "Creator analytics or digests are enabled.",
      "At least one course has learner activity to summarize.",
    ],
    expectedOutcome: [
      "Analytics are aggregate or scoped appropriately.",
      "Notification cadence is configurable.",
      "Exports or digests do not expose raw personal data that the creator does not need.",
    ],
    negativeVariant:
      "The analytics view exposes support-only fields, sensitive user notes, or other data outside creator scope.",
    auditFocus: ["privacy", "ux", "moderation_governance"],
  },
  {
    id: "I-11",
    roleCluster: "instructor_creator",
    accountIds: ["AC-12"],
    categories: ["content_creation_moderation", "onboarding_authentication"],
    commandText:
      "I want to assign a reviewer or co-instructor to one draft course without giving them access to unrelated drafts or billing controls.",
    preconditions: [
      "Reviewer or collaborator roles are supported in the test environment.",
      "The creator owns more than one draft or published course.",
    ],
    expectedOutcome: [
      "The collaborator receives only the intended scope.",
      "Role boundaries are visible in the invitation or permissions UI.",
      "All permission grants are logged.",
    ],
    negativeVariant:
      "A collaborator gains access to unrelated courses, learner billing details, or creator-wide settings.",
    auditFocus: ["security", "moderation_governance", "ux"],
  },
  {
    id: "A-01",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-11"],
    categories: ["support_operations", "onboarding_authentication"],
    commandText:
      "A user says signup fails because the email already exists. I need to resolve a duplicate-email or alias conflict safely.",
    preconditions: [
      "Support tooling exposes identity-safe duplicate-email diagnostics.",
      "The user can verify ownership through an approved recovery path.",
    ],
    expectedOutcome: [
      "The agent can distinguish existing account, alias conflict, and merge-review cases safely.",
      "The user receives a precise next step without exposing another person's account state.",
      "Any account merge or cleanup action is logged.",
    ],
    negativeVariant:
      "The agent can accidentally merge the wrong records or disclose whether another user's account exists beyond policy.",
    auditFocus: ["security", "ux", "moderation_governance"],
  },
  {
    id: "A-02",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-10"],
    categories: ["support_operations", "onboarding_authentication", "error_paths"],
    commandText:
      "A learner was locked after a suspicious-login alert. I need to unlock the account only after the right verification steps are complete.",
    preconditions: [
      "The support console exposes lock reason and verification checklist.",
      "The account is actually in a locked or risk-review state.",
    ],
    expectedOutcome: [
      "The support agent can verify identity without bypassing policy.",
      "Unlock actions revoke stale sessions if required.",
      "The account owner receives a clear recovery notice.",
    ],
    negativeVariant:
      "The account is unlocked without sufficient proof, or old sessions stay valid after the incident is resolved.",
    auditFocus: ["security", "reliability", "trust"],
  },
  {
    id: "A-03",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-07"],
    categories: ["support_operations", "course_discovery_enrollment_purchase"],
    commandText:
      "A learner's payment failed and they need an invoice copy. I need to help without seeing raw card data.",
    preconditions: [
      "Support billing view is available with redacted payment details.",
      "The user has an invoice or renewal history in the system.",
    ],
    expectedOutcome: [
      "The agent can see billing status, redacted payment metadata, and invoice history only.",
      "The invoice can be reissued or downloaded safely.",
      "Billing notes are consistent with user-facing entitlement state.",
    ],
    negativeVariant:
      "The support view exposes sensitive payment secrets or the invoice history does not match the actual entitlement record.",
    auditFocus: ["security", "billing", "privacy"],
  },
  {
    id: "A-04",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-07", "AC-04"],
    categories: ["support_operations", "course_discovery_enrollment_purchase"],
    commandText:
      "I need to process a refund, partial credit, or scholarship adjustment under policy and explain the entitlement impact.",
    preconditions: [
      "A transaction, scholarship record, or manual billing case exists.",
      "Refund and adjustment policies are documented.",
    ],
    expectedOutcome: [
      "The decision path and monetary effect are logged.",
      "The user sees whether access changes immediately, later, or not at all.",
      "Support can cite the applicable policy or pilot rule.",
    ],
    negativeVariant:
      "The refund is duplicated, the credit is applied to the wrong learner, or access is removed with no explanation.",
    auditFocus: ["billing", "trust", "reliability"],
  },
  {
    id: "A-05",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-17", "AC-09"],
    categories: ["support_operations", "data_rights_privacy"],
    commandText:
      "A guardian submitted consent for a minor learner. I need to verify the record and activate access only after approval is complete.",
    preconditions: [
      "The platform supports linked guardian-minor records.",
      "The learner account remains pending until consent is confirmed.",
    ],
    expectedOutcome: [
      "Guardian relationship and consent scope are logged with timestamps.",
      "Minor access activates only after successful approval.",
      "Support can explain revocation and community restrictions clearly.",
    ],
    negativeVariant:
      "Minor access opens before approval is finalized, or the consent record lacks enough detail to audit later.",
    auditFocus: ["privacy", "security", "moderation_governance"],
  },
  {
    id: "A-06",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-08"],
    categories: ["support_operations", "data_rights_privacy"],
    commandText:
      "A user requested a copy of all personal data under GDPR or CCPA. I need to fulfill it completely and only for the right person.",
    preconditions: [
      "An authenticated rights request or verified support workflow is available.",
      "The user has enough history to validate export completeness.",
    ],
    expectedOutcome: [
      "The export includes the documented user data categories and timestamps.",
      "The request lifecycle is logged end to end.",
      "The export excludes data belonging to other users or staff-only notes that should remain internal by policy.",
    ],
    negativeVariant:
      "A major data class is missing, or unrelated user data leaks into the export package.",
    auditFocus: ["privacy", "reliability", "data_integrity"],
  },
  {
    id: "A-07",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-08", "AC-11"],
    categories: ["support_operations", "data_rights_privacy"],
    commandText:
      "A user wants their account deleted. I need to complete the deletion and explain what must be retained by policy.",
    preconditions: [
      "Deletion is either self-serve or support-assisted with identity verification.",
      "Retention exceptions are documented.",
    ],
    expectedOutcome: [
      "Sessions are revoked and the account enters the documented deletion state.",
      "The user receives clear messaging about any retained billing, security, or abuse records.",
      "The deletion action is audit logged.",
    ],
    negativeVariant:
      "The user still has active access after deletion, or the support workflow cannot explain retained records.",
    auditFocus: ["privacy", "security", "trust"],
  },
  {
    id: "A-08",
    roleCluster: "admin_support",
    accountIds: ["AC-15"],
    categories: ["support_operations", "content_creation_moderation"],
    commandText:
      "A learner reported abusive community content. I need to review it, take action if needed, and preserve an appeal path.",
    preconditions: [
      "A moderation queue or abuse-report workflow exists.",
      "Trust-and-safety staff can see the report context and policy rules.",
    ],
    expectedOutcome: [
      "The moderation decision is logged with reason and timestamp.",
      "The affected user receives a notice consistent with policy.",
      "The appeal or review state is visible internally.",
    ],
    negativeVariant:
      "The action is overbroad, irreversible, or lacks an audit trail explaining why it happened.",
    auditFocus: ["moderation_governance", "trust", "security"],
  },
  {
    id: "A-09",
    roleCluster: "admin_support",
    accountIds: ["AC-14", "AC-15"],
    categories: ["support_operations", "error_paths", "notifications_preferences"],
    commandText:
      "Video streaming is degraded. I need to publish a clear public status update and give support agents a consistent message.",
    preconditions: [
      "A status surface or banner exists for public communication.",
      "Support staff can reference incident notes or canned responses.",
    ],
    expectedOutcome: [
      "The public status update is scoped, timestamped, and consistent with support guidance.",
      "The issue can be marked resolved or updated without leaving stale copy behind.",
      "Users know whether the workaround is retry, fallback download, or wait.",
    ],
    negativeVariant:
      "The status page, banner, and support responses drift apart or stay stale after the incident is fixed.",
    auditFocus: ["reliability", "ux", "trust"],
  },
  {
    id: "A-10",
    roleCluster: "admin_support",
    accountIds: ["AC-14"],
    categories: ["support_operations", "error_paths", "notifications_preferences"],
    commandText:
      "Users report rate-limit messages and unsupported-browser issues. I need to provide a precise, accessible resolution path.",
    preconditions: [
      "The product surfaces rate-limit or browser-support errors in a user-visible way.",
      "Support has guidance for retry windows and supported environments.",
    ],
    expectedOutcome: [
      "Messages explain the problem in plain language and avoid blame.",
      "Retry timing, supported browsers, and fallback options are explicit.",
      "Help content is readable and keyboard accessible.",
    ],
    negativeVariant:
      "The user only sees a generic failure page with no retry window, no browser guidance, and no accessible error summary.",
    auditFocus: ["ux", "accessibility", "reliability"],
  },
  {
    id: "A-11",
    roleCluster: "admin_support",
    accountIds: ["AC-15"],
    categories: ["support_operations", "data_rights_privacy"],
    commandText:
      "A report arrives through the public security disclosure channel. I need to acknowledge it and route it properly without unsafe back-and-forth.",
    preconditions: [
      "A public security disclosure contact or intake route exists.",
      "Trust-and-safety or engineering routing ownership is documented.",
    ],
    expectedOutcome: [
      "The report receives an acknowledgement within the documented response target.",
      "Internal escalation and ownership are recorded.",
      "Public responses avoid requesting risky public reproduction steps.",
    ],
    negativeVariant:
      "The report is lost, handled by the wrong queue, or answered with instructions that would weaken security posture.",
    auditFocus: ["security", "moderation_governance", "trust"],
  },
  {
    id: "M-01",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["course_discovery_enrollment_purchase", "support_operations"],
    commandText:
      "I want to start a 25-seat team trial or convert it into an annual enterprise plan with clear pricing and support commitments.",
    preconditions: [
      "Enterprise or pilot commercial routing exists in the test environment.",
      "The workspace can be created with a defined seat count.",
    ],
    expectedOutcome: [
      "Seat count, billing owner, term, and support expectations are explicit.",
      "The quote or trial state can be reviewed before activation.",
      "The manager receives a named next step for procurement or pilot support.",
    ],
    negativeVariant:
      "Seat limits, pricing assumptions, or support scope remain ambiguous after the commercial setup flow finishes.",
    auditFocus: ["ux", "billing", "trust"],
  },
  {
    id: "M-02",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["onboarding_authentication", "error_paths"],
    commandText:
      "I want to configure SSO, require MFA, and restrict access to my company domain before inviting my team.",
    preconditions: [
      "SSO or domain restriction is enabled in the test environment.",
      "A test identity provider is available if SSO is supported.",
    ],
    expectedOutcome: [
      "Configuration values are validated before go-live.",
      "A rollback or safe-test path exists before enforcing the policy for all seats.",
      "Auth rules are visible enough for a manager to understand the impact.",
    ],
    negativeVariant:
      "A bad SSO configuration or domain rule locks out valid users without a safe recovery path.",
    auditFocus: ["security", "reliability", "ux"],
  },
  {
    id: "M-03",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["course_discovery_enrollment_purchase", "notifications_preferences"],
    commandText:
      "I want to invite a cohort, assign a learning path, and see which seats are activated, pending, or unused.",
    preconditions: [
      "An enterprise workspace already exists.",
      "Invite and seat-state tracking are enabled.",
    ],
    expectedOutcome: [
      "Invite state is visible and refreshable.",
      "Assigned content matches the intended learning path.",
      "Reminder messaging is configurable and tied to real invitation status.",
    ],
    negativeVariant:
      "Expired or duplicate invites consume seats incorrectly or show the wrong activation state.",
    auditFocus: ["ux", "reliability"],
  },
  {
    id: "M-04",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["support_operations", "data_rights_privacy"],
    commandText:
      "An employee left the team. I want to reclaim or transfer the seat without losing the audit trail of completed training.",
    preconditions: [
      "A seat is currently assigned to a departing user.",
      "Transfer or reclaim rules are defined for the workspace.",
    ],
    expectedOutcome: [
      "The seat can be reclaimed or reassigned cleanly.",
      "Historical completion and access records remain attributable for reporting.",
      "The departing user's access ends on the correct date.",
    ],
    negativeVariant:
      "The seat is stuck, the history becomes orphaned, or the former user retains access after offboarding.",
    auditFocus: ["reliability", "privacy", "security"],
  },
  {
    id: "M-05",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["course_discovery_enrollment_purchase", "support_operations"],
    commandText:
      "I want to download invoices, PO references, and monthly seat-usage reports that match the contract period.",
    preconditions: [
      "Enterprise billing records exist in the test environment.",
      "The workspace has at least one completed billing cycle.",
    ],
    expectedOutcome: [
      "Invoices and seat reports align with the visible contract details.",
      "Files are downloadable and labeled by billing period.",
      "The manager can tell what is estimate versus final invoice data.",
    ],
    negativeVariant:
      "Seat counts, dates, or currencies differ between the dashboard and the downloadable invoice.",
    auditFocus: ["billing", "trust", "reliability"],
  },
  {
    id: "M-06",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["data_rights_privacy", "learning_experience"],
    commandText:
      "I want to review team progress without seeing private learner notes, support tickets, or unrelated personal data.",
    preconditions: [
      "A manager dashboard exists with scoped reporting.",
      "The workspace has at least a few invited or active learners.",
    ],
    expectedOutcome: [
      "The manager view is aggregate or role-appropriate by default.",
      "Sensitive learner data stays out of managerial reporting.",
      "Access boundaries are consistent across UI, exports, and notifications.",
    ],
    negativeVariant:
      "The manager can see private notes, raw support correspondence, or billing identifiers that are outside their role.",
    auditFocus: ["privacy", "security", "ux"],
  },
  {
    id: "M-07",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["support_operations", "data_rights_privacy"],
    commandText:
      "Before rollout, I want the DPA, security summary, retention commitments, and a named support or procurement contact.",
    preconditions: [
      "Partner-ready documentation exists or is routed through support.",
      "The manager can request materials without opening a generic learner ticket.",
    ],
    expectedOutcome: [
      "The right documents or support route are surfaced clearly.",
      "The manager sees who owns follow-up and expected response timing.",
      "Policy references match the current product behavior.",
    ],
    negativeVariant:
      "The request falls into a generic queue with no owner, stale documentation, or no response expectation.",
    auditFocus: ["trust", "privacy", "ux"],
  },
  {
    id: "M-08",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["notifications_preferences", "support_operations"],
    commandText:
      "I want weekly product digests, critical incident alerts immediately, and billing notices only to finance.",
    preconditions: [
      "Role-based or category-based notification preferences are available.",
      "More than one stakeholder email can be configured for the workspace if supported.",
    ],
    expectedOutcome: [
      "Notification categories are clearly separated by purpose.",
      "Urgent incident messages bypass the digest cadence when appropriate.",
      "Billing notices route only to the intended owner or finance contact.",
    ],
    negativeVariant:
      "Notifications are all-or-nothing, or high-volume digests drown out critical incident notices.",
    auditFocus: ["ux", "privacy", "reliability"],
  },
  {
    id: "M-09",
    roleCluster: "manager_guardian",
    accountIds: ["AC-17", "AC-09"],
    categories: ["data_rights_privacy", "notifications_preferences"],
    commandText:
      "I want to grant guardian consent for a minor learner, choose communication settings, and confirm what community features are disabled.",
    preconditions: [
      "A linked guardian-minor workflow exists.",
      "The minor account remains pending until consent is resolved.",
    ],
    expectedOutcome: [
      "Consent scope, community restrictions, and notification choices are explicit.",
      "The guardian can tell exactly what was approved.",
      "Revocation or change steps are documented.",
    ],
    negativeVariant:
      "The guardian cannot distinguish consent for learning access from consent for marketing, community participation, or analytics.",
    auditFocus: ["privacy", "ux", "moderation_governance"],
  },
  {
    id: "M-10",
    roleCluster: "manager_guardian",
    accountIds: ["AC-17", "AC-09"],
    categories: ["data_rights_privacy", "learning_experience"],
    commandText:
      "I want to view my linked minor's progress and request a correction or export of that learner's record only.",
    preconditions: [
      "The guardian account is linked to exactly one learner in the test setup.",
      "Progress and privacy-rights views are available for guardians if policy allows them.",
    ],
    expectedOutcome: [
      "The guardian sees only the linked learner's data.",
      "Correction or export requests are logged against the correct learner record.",
      "The UI distinguishes guardian rights from the learner's own account rights.",
    ],
    negativeVariant:
      "The guardian can see data from unrelated learners or cannot tell whether a request applies to the guardian or the child record.",
    auditFocus: ["privacy", "security", "data_integrity"],
  },
  {
    id: "M-11",
    roleCluster: "manager_guardian",
    accountIds: ["AC-16"],
    categories: ["data_rights_privacy", "support_operations", "error_paths"],
    commandText:
      "Our contract is ending. I want to export workspace data and close the organization safely without deleting anything before the export is ready.",
    preconditions: [
      "The workspace contains user, progress, and billing history.",
      "Org offboarding or workspace closure is supported in the test environment.",
    ],
    expectedOutcome: [
      "Export completes before destructive steps begin.",
      "The manager sees what will be retained by policy after closure.",
      "Access removal is timestamped and auditable.",
    ],
    negativeVariant:
      "The workspace deletion begins before export completion or no retention disclosure is shown during offboarding.",
    auditFocus: ["privacy", "reliability", "trust"],
  },
] as const;

export const AUDIT_ASSUMPTIONS = [
  "The learning platform supports first-party email/password accounts, and optional MFA or SSO may exist depending on the environment.",
  "Some commercial flows may be partner-scoped rather than public self-serve, so purchase-related commands can be executed as simulated or manual-review workflows in QA.",
  "Privacy-rights flows such as export and delete are either implemented or required for audit readiness.",
  "Minor accounts require guardian review, reduced communication scope, or a documented equivalent safeguard.",
  "Instructor, support, trust-and-safety, and manager roles should remain distinct so least-privilege checks can be audited explicitly.",
] as const;

export const AUDIT_USAGE_NOTES = [
  "These accounts are fictional fixtures for QA, demos, and audit evidence only.",
  "All identifiers are synthetic and must stay out of production as real user records.",
  "Commands are written as testable user intents and should be mapped to screenshots, logs, or tickets during validation.",
] as const;
