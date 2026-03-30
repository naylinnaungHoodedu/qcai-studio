export type SimulationTier = "Tier 1 - Conceptual" | "Tier 2 - Behavioral" | "Tier 3 - Physics-Accurate";
export type SimulationDifficulty = "Beginner" | "Intermediate" | "Advanced";

export type SimulationConcept = {
  id: string;
  title: string;
  tier: SimulationTier;
  summary: string;
  interaction: string;
  formula?: string;
  correction?: string;
  emphasis?: string;
};

export type SimulationModule = {
  moduleNumber: number;
  title: string;
  slug: string;
  summary: string;
  concepts: SimulationConcept[];
};

export type SimulationRecord = SimulationConcept & {
  slug: string;
  href: string;
  difficulty: SimulationDifficulty;
  moduleNumber: number;
  moduleSlug: string;
  moduleTitle: string;
  moduleSummary: string;
};

export type SimulationModuleEntry = Omit<SimulationModule, "concepts"> & {
  href: string;
  simulationCount: number;
  concepts: SimulationRecord[];
};

export type SimulationPrinciple = {
  title: string;
  summary: string;
  details?: string[];
};

export type SimulationState = {
  state: string;
  visualTreatment: string;
  purpose: string;
};

export type SimulationStackChoice = {
  requirement: string;
  choice: string;
  rationale: string;
};

export type SimulationEndpoint = {
  method: "GET" | "POST";
  path: string;
  purpose: string;
  extendsSurface: string;
};

export type SimulationPhase = {
  phase: string;
  deliverables: string;
  priority: string;
};

export const SIMULATION_STATUS_NOTE =
  "This page now includes browser-playable educational prototypes for all sixteen verified simulation concepts. They run live in the browser today, while session persistence, analytics, and lesson-embedded progression remain the next implementation layer.";

export const SIMULATION_TIERS = [
  {
    title: "Tier 1 - Conceptual",
    description:
      "Visual and classification-first simulations that make the idea legible before the learner reads the deeper explanation.",
  },
  {
    title: "Tier 2 - Behavioral",
    description:
      "Hands-on parameter and workflow manipulation where tradeoffs become visible through guided interaction and constrained goals.",
  },
  {
    title: "Tier 3 - Physics-Accurate",
    description:
      "Formula-backed, systems-level simulations that expose convergence, fidelity, energy, or solver behavior with quantitative outputs.",
  },
] as const;

export const SIMULATION_MODULES: SimulationModule[] = [
  {
    moduleNumber: 1,
    title: "NISQ realism and hybrid workload framing",
    slug: "nisq-hybrid-workflows",
    summary:
      "Module 1 simulations make the NISQ-era constraints visible and clarify where the quantum subroutine actually sits inside a hybrid workflow.",
    concepts: [
      {
        id: "SIM-01A",
        title: "The NISQ Fidelity Cliff",
        tier: "Tier 1 - Conceptual",
        summary:
          "Learners adjust circuit depth, gate error rate, qubit count, and backend assumptions while a live fidelity curve collapses from 1.0 toward 0.0.",
        interaction:
          "Controls include circuit depth, epsilon, qubit count, and backend options for IBM Heron, IonQ Forte, and a simulated ideal baseline.",
        formula: "F(G, epsilon) = (1 - epsilon)^G",
        correction:
          "Corrected as a conservative upper-bound model that uses total gate count G rather than depth times qubits. The 0.85 threshold is labeled as an illustrative teaching threshold, not a universal literature standard.",
        emphasis: "Recommended first build because it is the fastest high-value public demo and the clearest expression of the course thesis.",
      },
      {
        id: "SIM-01B",
        title: "QAI vs. AI4QC Decision Tree",
        tier: "Tier 1 - Conceptual",
        summary:
          "Ten real abstracts from the 2025 and 2026 proceedings are sorted into QAI or AI4QC with immediate reasoning feedback.",
        interaction:
          "Drag each abstract into the correct bucket, then inspect why the classification is right or wrong after every move.",
      },
      {
        id: "SIM-01C",
        title: "Hybrid Labor Split Visualizer",
        tier: "Tier 1 - Conceptual",
        summary:
          "A hybrid pipeline is split into classical preprocessing, quantum subroutine, and classical post-processing zones.",
        interaction:
          "Task cards such as normalization, gate compilation, parameter optimization, measurement averaging, and output decoding are dragged into the most plausible stage, then scored against cost and orchestration tradeoffs.",
      },
    ],
  },
  {
    moduleNumber: 2,
    title: "AI for routing, graph reduction, and constrained optimization",
    slug: "ai-for-quantum-hardware",
    summary:
      "Module 2 simulations focus on the classical support machinery that keeps near-term quantum workflows tractable under sparse hardware and small qubit budgets.",
    concepts: [
      {
        id: "SIM-02A",
        title: "Qubit Routing Sandbox",
        tier: "Tier 2 - Behavioral",
        summary:
          "A logical circuit is mapped onto a sparse coupling graph that mimics IBM Heron heavy-hex topology or a generic sparse backend.",
        interaction:
          "Learners manually insert SWAP operations, watch routing overhead accumulate, and compare their path with an AI-assisted router.",
        correction: "Corrected hardware reference from IBM Eagle to IBM Heron.",
      },
      {
        id: "SIM-02B",
        title: "Graph Shrinking Workshop",
        tier: "Tier 2 - Behavioral",
        summary:
          "A naive QUBO encoding starts above the available qubit budget and must be reduced through reformulation choices.",
        interaction:
          "Variable merging, penalty absorption, and subgraph factoring move the learner across a quality-versus-qubit scatter chart with a goal of staying under 10 qubits at greater than 90 percent quality.",
      },
      {
        id: "SIM-02C",
        title: "RL-Tuned Augmented Lagrangian Explorer",
        tier: "Tier 3 - Physics-Accurate",
        summary:
          "An industrial scheduling problem exposes primal and dual residual behavior under RL-tuned, fixed, and human-tuned penalty strategies.",
        interaction:
          "Learners adjust lambda, RL learning rate, and ADMM iteration count, then inspect convergence curves and compare policy quality across strategies.",
      },
    ],
  },
  {
    moduleNumber: 3,
    title: "Hybrid application architectures and kernel decisions",
    slug: "quantum-enhanced-applications",
    summary:
      "Module 3 simulations focus on application architecture decisions, kernel behavior, and how hybrid models should be decomposed and evaluated.",
    concepts: [
      {
        id: "SIM-03A",
        title: "Hybrid Architecture Dissector",
        tier: "Tier 1 - Conceptual",
        summary:
          "Five paper-derived pipelines are decomposed into input, classical encoder, quantum layer, classical decoder, and output stages.",
        interaction:
          "Learners inspect each layer, compare architectures side by side, and see how the quantum layer changes the end-to-end design rather than replacing it.",
      },
      {
        id: "SIM-03B",
        title: "Quantum Kernel vs. Classical Kernel Comparator",
        tier: "Tier 3 - Physics-Accurate",
        summary:
          "A synthetic biomedical dataset shows how an RBF SVM and a quantum-kernel SVM behave as dimensionality scales upward.",
        interaction:
          "Decision boundaries update live while the learner increases dimensionality and compares where quantum feature maps plausibly help or collapse back to parity.",
      },
      {
        id: "SIM-03C",
        title: "Few-Shot Learning Episode Builder",
        tier: "Tier 2 - Behavioral",
        summary:
          "Few-shot episodes expose how support-set size, embedding depth, and classical-head choice affect accuracy.",
        interaction:
          "Accuracy-versus-K curves update in real time, revealing where quantum embedding helps at K=1 and where classical parity returns by K=10.",
      },
    ],
  },
  {
    moduleNumber: 4,
    title: "Representation, compression, and explainability",
    slug: "representation-explainability",
    summary:
      "Module 4 simulations make representational tradeoffs visible, especially where quantum structure is used for compression or explanation acceleration.",
    concepts: [
      {
        id: "SIM-04A",
        title: "quINR Compression Rate Explorer",
        tier: "Tier 2 - Behavioral",
        summary:
          "A full-resolution image or signal is compressed with both a classical INR and a quINR so the learner can compare compression ratio and PSNR.",
        interaction:
          "Quantum parameter count changes the quality-compression frontier while a residual viewer reveals which spectral components are captured more efficiently.",
      },
      {
        id: "SIM-04B",
        title: "QGSHAP Explainability Accelerator",
        tier: "Tier 2 - Behavioral",
        summary:
          "A GNN over a molecular graph compares classical SHAP evaluation cost with a QGSHAP path that uses amplitude amplification.",
        interaction:
          "Matching explanation quality is held fixed while the learner watches computational cost fall from exhaustive or sampled classical evaluation toward a quantum-assisted square-root sample regime.",
        formula: "Classical exact cost O(2^N), sampled cost O(M), QGSHAP cost O(sqrt(M))",
      },
    ],
  },
  {
    moduleNumber: 5,
    title: "Industry deployment, optimization, and post-quantum migration",
    slug: "industry-use-cases",
    summary:
      "Module 5 simulations translate the course into deployment realism: solver tradeoffs, migration strategy, vertical prioritization, and time-horizon judgment.",
    concepts: [
      {
        id: "SIM-05A",
        title: "Quantum vs. Classical Solver Race",
        tier: "Tier 3 - Physics-Accurate",
        summary:
          "Three solvers attack the same logistics-style optimization problem while cost and runtime update every 500 milliseconds.",
        interaction:
          "Problem size reveals crossover behavior across brute force, simulated annealing, and a D-Wave-style QUBO path, with a hardware cost panel included for business realism.",
      },
      {
        id: "SIM-05B",
        title: "Post-Quantum Cryptography Migration Simulator",
        tier: "Tier 2 - Behavioral",
        summary:
          "A twelve-service infrastructure is triaged under escalating quantum threat, forcing the learner to decide which cryptographic assets actually require migration.",
        interaction:
          "Services using RSA-2048, ECC-256, AES-128, and AES-256 are examined under time pressure so the learner separates urgent migration from good operational hygiene.",
        correction:
          "Critical correction applied: AES-256 does not require PQC migration. AES-128 is upgraded to AES-256 as hygiene, while RSA-2048 maps to ML-KEM, ECC-256 to ML-DSA, and signature systems to SLH-DSA under the relevant FIPS standards.",
      },
      {
        id: "SIM-05C",
        title: "Industry Vertical Mapper",
        tier: "Tier 1 - Conceptual",
        summary:
          "A Sankey-style map connects industry verticals to QC+AI application types, maturity levels, and deployment horizons.",
        interaction:
          "Each connection can be filtered and opened against the source passage in the industry-use-case document so commercial narratives stay tied to evidence.",
      },
    ],
  },
  {
    moduleNumber: 6,
    title: "Thermodynamics and future-roadmap reasoning",
    slug: "thermodynamics-roadmap",
    summary:
      "Module 6 simulations turn the closing roadmap material into measurable tradeoff surfaces instead of abstract future-state claims.",
    concepts: [
      {
        id: "SIM-06A",
        title: "Thermodynamic Cost Calculator",
        tier: "Tier 2 - Behavioral",
        summary:
          "A hybrid scheduling or optimization agent exposes energy cost, memory cost, and solution quality as coupled live outputs.",
        interaction:
          "Learners vary classical compute allocation, quantum QPU shots, and memory architecture while searching for a Pareto frontier against the Landauer limit reference line.",
        formula: "Landauer limit E_min = kT ln(2) per bit erasure, about 4 x 10^-21 J at 300K",
      },
      {
        id: "SIM-06B",
        title: "Near-Term vs. Speculative Roadmap Sorter",
        tier: "Tier 1 - Conceptual",
        summary:
          "Claims from the 2026 synthesis are sorted across time horizon and evidence strength rather than being accepted at face value.",
        interaction:
          "Learners drag thirty claims onto a canvas with axes for time horizon and evidence strength, then compare their placements with the source authors' reasoning.",
      },
    ],
  },
];

function slugifySimulationTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function difficultyFromTier(tier: SimulationTier): SimulationDifficulty {
  switch (tier) {
    case "Tier 1 - Conceptual":
      return "Beginner";
    case "Tier 2 - Behavioral":
      return "Intermediate";
    case "Tier 3 - Physics-Accurate":
      return "Advanced";
    default:
      return "Intermediate";
  }
}

export const SIMULATION_MODULE_ENTRIES: SimulationModuleEntry[] = SIMULATION_MODULES.map((module) => {
  const concepts = module.concepts.map<SimulationRecord>((concept) => {
    const slug = slugifySimulationTitle(concept.title);
    return {
      ...concept,
      slug,
      href: `/simulations/${slug}`,
      difficulty: difficultyFromTier(concept.tier),
      moduleNumber: module.moduleNumber,
      moduleSlug: module.slug,
      moduleTitle: module.title,
      moduleSummary: module.summary,
    };
  });

  return {
    ...module,
    href: `/simulations#module-${module.slug}`,
    simulationCount: concepts.length,
    concepts,
  };
});

export const SIMULATION_RECORDS = SIMULATION_MODULE_ENTRIES.flatMap((module) => module.concepts);
export const SIMULATION_SLUGS = SIMULATION_RECORDS.map((simulation) => simulation.slug);
export const SIMULATION_ROUTE_LASTMOD: Record<string, string> = Object.fromEntries(
  SIMULATION_RECORDS.map((simulation) => [simulation.slug, "2026-03-30T00:00:00Z"]),
);

export function getSimulationBySlug(slug: string): SimulationRecord | null {
  return SIMULATION_RECORDS.find((simulation) => simulation.slug === slug) ?? null;
}

export function getSimulationModuleEntry(slug: string): SimulationModuleEntry | null {
  return SIMULATION_MODULE_ENTRIES.find((module) => module.slug === slug) ?? null;
}

export const SIMULATION_PRINCIPLES: SimulationPrinciple[] = [
  {
    title: "Simulation as lesson, not supplement",
    summary:
      "The intended sequence is simulation first, then source-grounded explanation, then flashcards and quiz work. The learner should encounter the phenomenon before reading the abstract account of it.",
  },
  {
    title: "Three-state interface",
    summary:
      "Every simulation should support an intuitive progression from open play to constrained task execution and then to explanation.",
  },
  {
    title: "Source citation on every output",
    summary:
      "Every simulation state should resolve back to the corpus passage that justifies it so the product stays trustworthy instead of drifting into generic illustration.",
  },
  {
    title: "Simulation state as a study object",
    summary:
      "Session state should be saveable, reloadable, annotatable, comparable, and eligible for project submission so the labs tie into notes, analytics, and portfolio work.",
  },
  {
    title: "Progressive disclosure of complexity",
    summary:
      "Basic mode should stay public and legible, advanced mode should unlock after related quiz completion, and expert mode should expose model-level controls only after deeper work.",
  },
  {
    title: "Failure is informative, not punitive",
    summary:
      "When a configuration fails, the UI should explain what parameter caused the failure, suggest one concrete adjustment, and preserve the failed state because it is pedagogically valuable.",
  },
  {
    title: "Arena integration",
    summary:
      "Each simulation should have a competitive variant so the existing Arena surface can host substantive technical tasks instead of recall-only prompts.",
  },
];

export const SIMULATION_STATES: SimulationState[] = [
  {
    state: "Explore",
    visualTreatment: "Free interaction with no timer and minimal guidance.",
    purpose: "Build intuition through play and visible cause-and-effect.",
  },
  {
    state: "Challenge",
    visualTreatment: "System-defined goal with constraints and scoring active.",
    purpose: "Force applied reasoning under realistic tradeoffs and time pressure.",
  },
  {
    state: "Explain",
    visualTreatment: "Optimal or reference solution is revealed with source-linked reasoning.",
    purpose: "Close the loop so the learner understands not only what worked but why.",
  },
];

export const SIMULATION_ARCHITECTURE_NOTES = [
  {
    title: "Current runtime foundation",
    bullets: [
      "The live frontend already runs on Next.js 16.2.1, React 19.2.4, TypeScript, and App Router.",
      "The backend already exposes FastAPI, SQLAlchemy, analytics, projects, arena, and search surfaces that a simulation program can extend rather than replace.",
      "Guest-mode browsing and structured public content already exist, which makes browser-first simulation demos a credible next step.",
    ],
  },
  {
    title: "Recommended browser-side additions",
    bullets: [
      "D3.js and the Canvas API for fidelity curves, charts, graph layouts, and cost surfaces.",
      "Three.js for any future Bloch-sphere or richer three-dimensional visualizations.",
      "Zustand as a lightweight state store if the simulation layer outgrows local component state, with React Context kept as a zero-dependency fallback.",
      "TensorFlow.js only where browser-side inference is genuinely needed; otherwise the simulation layer should stay lightweight.",
    ],
  },
  {
    title: "Corrected technical constraints",
    bullets: [
      "The fidelity model uses total noisy gate count G, not depth times qubits, and must be labeled as a conservative teaching model.",
      "Statevector storage should prefer interleaved Float64Array layouts once simulations push beyond small qubit counts to reduce garbage-collection pressure.",
      "Post-quantum migration logic must keep symmetric-key guidance separate from public-key migration so the learner is not taught incorrect cryptographic risk.",
    ],
  },
] as const;

export const SIMULATION_STACK_CHOICES: SimulationStackChoice[] = [
  {
    requirement: "Pure browser delivery with zero install friction",
    choice: "React + Canvas API + targeted D3.js visualizations",
    rationale: "Fits the existing web product and keeps public guest demos easy to load and share.",
  },
  {
    requirement: "Fidelity curves, routing charts, and qubit-quality tradeoffs",
    choice: "D3.js v7 or equivalent lightweight charting primitives",
    rationale: "Good fit for animated SVG or canvas-based explanatory charts without pushing the app into a heavyweight graphics stack.",
  },
  {
    requirement: "Graph and topology rendering",
    choice: "Force-directed or custom D3 graph layouts",
    rationale: "Well suited to routing maps, coupling graphs, and QUBO reduction workflows.",
  },
  {
    requirement: "Client-side quantum state math for small systems",
    choice: "Custom TypeScript statevector utilities",
    rationale: "Enough for education-scale simulations without introducing opaque black-box libraries.",
  },
  {
    requirement: "Real-time competitive variants",
    choice: "Existing WebSocket and arena surfaces with Redis-style pub/sub if needed",
    rationale: "Aligns with the current Arena model and supports ranked or timed challenges.",
  },
];

export const SIMULATION_ENDPOINTS: SimulationEndpoint[] = [
  {
    method: "POST",
    path: "/simulations/session",
    purpose: "Save simulation state, parameters, outcome, and timestamp.",
    extendsSurface: "New simulation route group",
  },
  {
    method: "GET",
    path: "/simulations/session/{id}",
    purpose: "Reload a saved simulation state for continued study or review.",
    extendsSurface: "New simulation route group",
  },
  {
    method: "POST",
    path: "/simulations/compare",
    purpose: "Compare two saved runs side by side.",
    extendsSurface: "New simulation route group",
  },
  {
    method: "GET",
    path: "/simulations/source-citation",
    purpose: "Resolve simulation state to the corpus passage that supports the output.",
    extendsSurface: "Extends search and citation surfaces",
  },
  {
    method: "POST",
    path: "/simulations/arena/challenge",
    purpose: "Create a competitive simulation challenge session.",
    extendsSurface: "Extends Arena",
  },
  {
    method: "GET",
    path: "/simulations/leaderboard/{sim_id}",
    purpose: "Fetch rankings for a specific simulation challenge.",
    extendsSurface: "Extends Arena",
  },
  {
    method: "POST",
    path: "/analytics/simulation-event",
    purpose: "Log learner interaction events for dashboards and skill-gap reporting.",
    extendsSurface: "Extends analytics",
  },
];

export const SIMULATION_PHASES: SimulationPhase[] = [
  {
    phase: "Phase 0 - Foundation",
    deliverables:
      "Simulation shell component, state store, TypeScript simulator utilities, seven API endpoints, analytics wiring, and a source-citation resolver.",
    priority: "Blocker for every later phase.",
  },
  {
    phase: "Phase 1 - Module 1 public launch",
    deliverables:
      "SIM-01A and SIM-01C embedded in the NISQ lesson flow, with simulation completion unlocking advanced study prompts.",
    priority: "Highest immediate learner impact.",
  },
  {
    phase: "Phase 2 - Module 2 differentiation",
    deliverables:
      "SIM-02A and SIM-02B, plus an Arena variant of the routing sandbox.",
    priority: "Highest technical differentiation.",
  },
  {
    phase: "Phase 3 - Module 5 business relevance",
    deliverables:
      "SIM-05A and SIM-05B, with corrected post-quantum migration logic and project integration.",
    priority: "Highest commercial and portfolio relevance.",
  },
  {
    phase: "Phase 4 - Full curriculum coverage",
    deliverables:
      "SIM-04B, SIM-06A, SIM-06B, and additional Arena variants for the most demonstrable labs.",
    priority: "Completes coverage across the course path.",
  },
  {
    phase: "Phase 5 - Polish and public demo hardening",
    deliverables:
      "Comparison mode, export and share flows, mobile-optimized layouts, and a guest-access teaser set of simulations.",
    priority: "Raises the platform credibility ceiling.",
  },
];

export const SIMULATION_FOUNDATION_CHECKLIST = [
  "SimulationShell component with basic, advanced, and expert mode switching plus annotation support.",
  "TypeScript simulator utilities for statevector updates, noise channels, and conservative fidelity computation.",
  "Session save and load endpoints so simulation state becomes part of the learner record.",
  "Analytics event capture wired into the existing dashboard and skills infrastructure.",
  "Lesson embedding pattern that mounts simulations as native React surfaces instead of iframes.",
  "Citation resolution so each meaningful output can be traced back to the source corpus.",
] as const;

export const SIMULATION_VERIFIED_ITEMS = [
  "The six-module structure and current learning goals align with the live syllabus.",
  "The simulation paper references such as quINR, QuCoWE, and QGSHAP match the current source framing.",
  "The QAI versus AI4QC distinction is consistent with Module 1 learning objectives.",
  "IBM heavy-hex topology references are compatible with the routing-sandbox framing.",
  "Standard Kraus-operator style noise channels remain the correct formal basis for quantum noise demonstrations.",
  "Statevector sizing still scales as 2^n complex amplitudes for n qubits.",
  "FIPS 203, 204, and 205 remain the right standards anchors for the post-quantum migration simulation.",
  "Grover-style square-root speedup remains the correct high-level framing for QGSHAP acceleration claims.",
  "The Landauer limit remains the right theoretical baseline for the thermodynamic calculator.",
] as const;

export const SIMULATION_FIRST_STEP = {
  id: "SIM-01A",
  title: "Build the NISQ Fidelity Cliff first",
  summary:
    "It is the simplest complete public demo, the most directly tied to the course thesis, and the fastest way to change the first impression of the platform from brochure to learn-by-doing studio.",
} as const;
