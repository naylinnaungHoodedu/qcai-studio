export const COURSE_SCOPE_NOTE =
  "QC+AI Studio now spans an eleven-module public curriculum with twelve lesson entry points. It remains a hardware-constrained studio path rather than a finished fifteen-week academy, but it now extends well beyond the original seven-lesson starter track.";

export const TARGET_AUDIENCE = [
  "Graduate students, engineers, and technical professionals exploring the QC+AI boundary.",
  "Learners who want hardware-aware hybrid-system thinking instead of purely abstract quantum exposition.",
  "Builders who want a compact, inspectable curriculum before deeper specialization.",
] as const;

export const ABOUT_AUDIENCE_GROUPS = [
  {
    title: "Students",
    description:
      "Undergraduate and graduate learners who want a structured entry into hybrid quantum-classical systems without starting from marketing language.",
    icon: "students",
  },
  {
    title: "Developers",
    description:
      "Software engineers moving toward quantum programming, compiler-aware workflows, and hardware-constrained software design.",
    icon: "developers",
  },
  {
    title: "Data scientists",
    description:
      "Applied ML and optimization practitioners evaluating where quantum kernels, compressed features, or QUBO reformulations may actually fit.",
    icon: "scientists",
  },
  {
    title: "Researchers",
    description:
      "Academic and industry researchers who need a compact, inspectable view of current QC+AI evidence, limits, and deployment tradeoffs.",
    icon: "researchers",
  },
] as const;

export const ABOUT_LEARNING_PROGRESSION = [
  {
    title: "Foundations",
    summary: "NISQ realism, hybrid-system framing, and why hardware limits dominate the early design conversation.",
    moduleRange: "Modules 1 and 7",
  },
  {
    title: "Algorithms",
    summary: "Routing, constrained optimization, kernels, and the validation logic behind hardware-aware QC+AI models.",
    moduleRange: "Modules 2 and 8",
  },
  {
    title: "Programming",
    summary: "Device-first programming patterns, parameter-shift workflows, shot strategy, debugging, and compiler-aware execution.",
    moduleRange: "Modules 9 and 10",
  },
  {
    title: "Applications",
    summary: "Vision, healthcare, language, explainability, and industry use cases interpreted through realistic deployment constraints.",
    moduleRange: "Modules 3, 4, and 5",
  },
  {
    title: "Specialization",
    summary: "Systems-roadmap thinking and finance-focused optimization work that push the curriculum into domain-specific tradeoffs.",
    moduleRange: "Modules 6 and 11",
  },
] as const;

export const PREREQUISITES = [
  "Comfort reading technical material in linear algebra terms such as vectors, matrices, embeddings, and similarity.",
  "Basic machine-learning intuition: optimization, feature representations, evaluation, and the role of training loops.",
  "General programming literacy for reading code, APIs, architecture diagrams, or experiment workflows.",
  "Prior professional quantum-computing experience is not required, but some exposure to qubits, gates, or NISQ-era limits helps.",
] as const;

export const ENGINEERING_READING_NOTES = [
  "Treat the quantum component as a bounded systems decision, not as a blanket replacement for the classical stack.",
  "Ask what physical bottleneck moved: routing depth, graph size, calibration burden, data encoding, or validation complexity.",
  "Read every application claim against a classical baseline and a concrete deployment constraint.",
] as const;

export const INDUSTRY_METHOD_NOTE =
  "Module 5 is intentionally framed as applied and commercial synthesis. It draws from the curated industry-use-case source to teach adoption patterns, sector readiness, and deployment constraints, rather than presenting itself as proceedings-style peer-reviewed evidence.";

export const GUEST_MODE_NOTES = [
  "Public visitors can browse curriculum pages and use guest-mode study surfaces in the current browser session.",
  "Guest activity is stored per browser session. Cross-device continuity requires authenticated identity when Auth0 client configuration is enabled for the deployment.",
  "Search and Q&A remain citation-grounded. When Pinecone or OpenAI secrets are not provisioned, the site transparently falls back to grounded lexical retrieval.",
] as const;

export const PROJECT_PREVIEW = [
  {
    slug: "routing-rescue-playbook",
    title: "Routing Rescue Playbook",
    deliverable:
      "Architecture memo with routing strategy, graph-shrinking plan, and validation checkpoints.",
    rubric: [
      "Systems grounding: shows concrete awareness of routing overhead, sparsity, and hardware bottlenecks.",
      "Optimization design: explains how reformulation, graph shrinking, or classical control loops improve tractability.",
      "Validation plan: includes realistic success metrics, fallbacks, and classical baselines.",
    ],
  },
  {
    slug: "hybrid-clinical-decision-brief",
    title: "Hybrid Clinical Decision Brief",
    deliverable:
      "Clinical-design brief covering model boundaries, explainability, and deployment guardrails.",
    rubric: [
      "Application fit: chooses a plausible quantum bottleneck instead of replacing the whole workflow.",
      "Safety and explainability: addresses failure modes, human oversight, and regulated use.",
      "Evidence quality: grounds claims in the course corpus instead of generic advantage language.",
    ],
  },
  {
    slug: "post-quantum-migration-roadmap",
    title: "Post-Quantum Migration Roadmap",
    deliverable:
      "Risk and execution roadmap with phased milestones, communication plan, and readiness checkpoints.",
    rubric: [
      "Risk prioritization: separates urgent migration risks from longer-horizon opportunities.",
      "Stakeholder strategy: aligns technical, regulatory, and commercial actors.",
      "Roadmap quality: defines phases, dependencies, and measurable readiness signals.",
    ],
  },
] as const;
