export type AcademyDifficulty = "Beginner" | "Intermediate" | "Advanced";
export type AcademyAccent = "cyan" | "violet" | "emerald" | "rose" | "amber";

export type AcademySimulation = {
  id: string;
  slug: string;
  title: string;
  difficulty: AcademyDifficulty;
  tagline: string;
  summary: string;
  description: string;
  formula?: string;
};

export type AcademySubject = {
  slug: string;
  title: string;
  summary: string;
  eyebrow: string;
  accent: AcademyAccent;
  accentColor: string;
  iconLabel: string;
  simulations: AcademySimulation[];
};

export type AcademySubjectRecord = AcademySubject & {
  href: string;
  simulationCount: number;
};

export type AcademySimulationRecord = AcademySimulation & {
  href: string;
  subjectSlug: string;
  subjectTitle: string;
  subjectSummary: string;
  subjectHref: string;
  subjectAccent: AcademyAccent;
  subjectAccentColor: string;
  subjectIconLabel: string;
};

export const ACADEMY_SUBJECTS: AcademySubject[] = [
  {
    slug: "quantum-mechanics-and-information",
    title: "Quantum Mechanics & Information",
    summary:
      "Explore state geometry, superposition, interference, tunneling, entanglement, and measurement collapse through visual-first interactive labs.",
    eyebrow: "Math subjects",
    accent: "cyan",
    accentColor: "#63d8ff",
    iconLabel: "QI",
    simulations: [
      {
        id: "QMI-01",
        slug: "bloch-sphere-visualizer",
        title: "Bloch Sphere Visualizer",
        difficulty: "Beginner",
        tagline: "Interactively explore qubit states, rotations, and measurement axes.",
        summary:
          "Control polar and azimuthal angles, apply common single-qubit gates, and watch the qubit move through the Bloch sphere coordinate system.",
        description:
          "This lab turns the single-qubit state into a geometric object so learners can connect amplitudes, phases, and measurement probabilities to a visible orientation in space.",
        formula: "|psi> = cos(theta/2)|0> + e^{i phi} sin(theta/2)|1>",
      },
      {
        id: "QMI-02",
        slug: "quantum-superposition-explorer",
        title: "Quantum Superposition Explorer",
        difficulty: "Beginner",
        tagline: "Visualize how alpha|0> + beta|1> responds to basis changes and phase shifts.",
        summary:
          "Tune amplitudes and relative phase, then compare how the same state looks under computational, Hadamard, and custom measurement bases.",
        description:
          "The goal is to make superposition feel operational rather than mystical by connecting coefficients to the probabilities and interference patterns that a measurement basis reveals.",
      },
      {
        id: "QMI-03",
        slug: "quantum-interference-lab",
        title: "Quantum Interference",
        difficulty: "Intermediate",
        tagline: "See constructive and destructive interference in amplitude evolution.",
        summary:
          "Adjust path length, wavelength, amplitude, and detector distance to move between bright and dark interference outcomes.",
        description:
          "This lab gives learners a two-path interference mental model that links phase accumulation to fringe spacing, contrast, and the observable detector intensity.",
      },
      {
        id: "QMI-04",
        slug: "quantum-tunneling-simulator",
        title: "Quantum Tunneling",
        difficulty: "Intermediate",
        tagline: "Simulate a packet tunneling through adjustable potential barriers.",
        summary:
          "Vary barrier width, barrier height, and packet energy to see when transmission collapses and when wave behavior still leaks through.",
        description:
          "The lab is designed as an intuition-builder for why quantum transport differs from a classical particle model at the same energy budget.",
      },
      {
        id: "QMI-05",
        slug: "bell-state-entanglement-simulator",
        title: "Entanglement Lab",
        difficulty: "Intermediate",
        tagline: "Create Bell states and visualize their correlation patterns.",
        summary:
          "Pick a Bell state, rotate Alice and Bob measurement settings, and inspect how expectation values and correlation strength change.",
        description:
          "The lab emphasizes how entanglement is encoded in joint measurement behavior rather than in two isolated local states.",
      },
      {
        id: "QMI-06",
        slug: "measurement-collapse-simulator",
        title: "Measurement Collapse Simulator",
        difficulty: "Beginner",
        tagline: "Watch how repeated measurements collapse a superposed state.",
        summary:
          "Set the state angle, choose a measurement basis, and run repeated shots to compare expected probabilities against sampled outcomes.",
        description:
          "This lab helps learners distinguish pre-measurement amplitudes from post-measurement outcomes and build intuition for Born-rule sampling.",
      },
    ],
  },
  {
    slug: "quantum-algorithms",
    title: "Quantum Algorithms",
    summary:
      "Step through core algorithmic ideas such as teleportation, Deutsch-Jozsa, the QFT, Shor-style period finding, and Grover amplification.",
    eyebrow: "Algorithm subjects",
    accent: "violet",
    accentColor: "#8f6bff",
    iconLabel: "QA",
    simulations: [
      {
        id: "QAL-01",
        slug: "quantum-teleportation-explorer",
        title: "Quantum Teleportation Explorer",
        difficulty: "Intermediate",
        tagline: "Step through the full quantum teleportation protocol.",
        summary:
          "Prepare a message qubit, entangle a resource pair, then inspect the classical correction needed to recover the remote state.",
        description:
          "The lab is a protocol walkthrough rather than a black-box animation, so each classical bit and correction gate remains visible.",
      },
      {
        id: "QAL-02",
        slug: "deutsch-jozsa-algorithm",
        title: "Deutsch-Jozsa Algorithm",
        difficulty: "Intermediate",
        tagline: "See how one oracle query separates balanced from constant functions.",
        summary:
          "Switch between balanced and constant oracle families, run the circuit, and inspect the final measurement signature.",
        description:
          "The lab frames Deutsch-Jozsa as an early lesson in interference-based algorithmic structure rather than a scalability claim.",
      },
      {
        id: "QAL-03",
        slug: "quantum-fourier-transform-visualizer",
        title: "Quantum Fourier Transform Visualizer",
        difficulty: "Advanced",
        tagline: "Map basis states into periodic frequency structure with the QFT.",
        summary:
          "Choose register size and input basis patterns, then inspect how the transformed state concentrates around periodic peaks.",
        description:
          "This lab focuses on the QFT as a representational transform, making phase structure legible before Shor-style period finding is introduced.",
      },
      {
        id: "QAL-04",
        slug: "shors-algorithm-period-finding",
        title: "Shor's Algorithm",
        difficulty: "Advanced",
        tagline: "Factor small composites using the period-finding workflow.",
        summary:
          "Pick a small composite and a valid base, run the period-finding step, and inspect how classical post-processing recovers non-trivial factors.",
        description:
          "The lab stays deliberately small and pedagogical so learners see where the quantum subroutine ends and where classical number theory takes over.",
      },
      {
        id: "QAL-05",
        slug: "grovers-search-amplitude-amplification",
        title: "Grover's Search",
        difficulty: "Intermediate",
        tagline: "Visualize repeated Grover iterations and amplitude amplification.",
        summary:
          "Choose a search space, mark a target, and watch the probability mass rotate toward the target state as iteration count changes.",
        description:
          "The lab uses the geometric amplitude-amplification picture so learners can see why too many iterations overshoot the target.",
      },
    ],
  },
  {
    slug: "quantum-programming",
    title: "Quantum Programming",
    summary:
      "Practice gate sequencing, small-circuit construction, Qiskit-style code generation, and statevector reasoning in a browser-first environment.",
    eyebrow: "Programming subjects",
    accent: "emerald",
    accentColor: "#38d39f",
    iconLabel: "QP",
    simulations: [
      {
        id: "QPR-01",
        slug: "unitary-operations-playground",
        title: "Unitary Operations Playground",
        difficulty: "Intermediate",
        tagline: "Interact with Pauli, Hadamard, phase-shift, and rotation gates.",
        summary:
          "Build a single-qubit gate sequence, watch the state update after each operation, and compare amplitudes before and after collapse.",
        description:
          "The focus is on helping learners internalize how unitary gate composition changes amplitudes and measurement probabilities step by step.",
      },
      {
        id: "QPR-02",
        slug: "qiskit-circuit-lab",
        title: "Qiskit Circuit Lab",
        difficulty: "Intermediate",
        tagline: "Build circuits visually and export a Qiskit-style code sketch.",
        summary:
          "Place gates on a small grid, inspect the generated circuit listing, and compare the visual circuit against a Python-flavored pseudo-export.",
        description:
          "The lab is meant as a bridge from visual learning into code literacy, not as a full IDE replacement.",
      },
      {
        id: "QPR-03",
        slug: "statevector-simulator",
        title: "Statevector Simulator",
        difficulty: "Intermediate",
        tagline: "Simulate small multi-qubit circuits and inspect amplitudes directly.",
        summary:
          "Run toy presets or custom sequences on a small register, then inspect complex amplitudes and basis-state probabilities.",
        description:
          "This lab turns the statevector from an abstract notation into a readable debugging object for small educational circuits.",
      },
    ],
  },
  {
    slug: "advanced-quantum-software",
    title: "Advanced Quantum Software",
    summary:
      "Explore error-correction logic, syndrome decoding, and hybrid quantum-classical learning loops through compact engineering-focused prototypes.",
    eyebrow: "Software subjects",
    accent: "rose",
    accentColor: "#f368b4",
    iconLabel: "AS",
    simulations: [
      {
        id: "AQS-01",
        slug: "quantum-error-correction-lab",
        title: "Quantum Error Correction Lab",
        difficulty: "Advanced",
        tagline: "Explore bit-flip codes, syndrome triggers, and visual decoder logic.",
        summary:
          "Inject simple X, Z, or Y errors into a small code family, inspect the syndrome, and compare the decoder recommendation against the true fault.",
        description:
          "The lab keeps the code families compact on purpose so the learner can focus on stabilizer logic and correction flow instead of implementation overhead.",
      },
      {
        id: "AQS-02",
        slug: "hybrid-quantum-classical-ml-lab",
        title: "Hybrid Quantum-Classical ML",
        difficulty: "Advanced",
        tagline: "Visualize variational circuits and optimization landscapes.",
        summary:
          "Adjust ansatz family, optimizer, and model parameters while a toy loss landscape and validation score update in response.",
        description:
          "The lab treats hybrid ML as a systems-and-optimization problem rather than claiming magical accuracy gains.",
      },
    ],
  },
  {
    slug: "quantum-finance-and-optimization",
    title: "Quantum Finance & Optimization",
    summary:
      "Connect quantum-inspired optimization and Monte Carlo ideas to concrete finance-style decisions around allocation, pricing, and risk.",
    eyebrow: "Finance subjects",
    accent: "amber",
    accentColor: "#f9a511",
    iconLabel: "QF",
    simulations: [
      {
        id: "QFO-01",
        slug: "qaoa-portfolio-optimization-lab",
        title: "QAOA Portfolio Optimization",
        difficulty: "Advanced",
        tagline: "Optimize toy portfolios with a QAOA-inspired risk/return model.",
        summary:
          "Vary portfolio style, risk aversion, optimizer, and mixing parameters to compare expected return, volatility, and objective score.",
        description:
          "The lab is framed as a quantum-inspired decision surface, keeping the financial tradeoffs visible rather than burying them behind solver jargon.",
      },
      {
        id: "QFO-02",
        slug: "quantum-monte-carlo-option-pricing-lab",
        title: "Quantum Monte Carlo",
        difficulty: "Intermediate",
        tagline: "Price simple options with Monte Carlo and amplitude-estimation intuition.",
        summary:
          "Tune the option contract and market parameters, then compare a classical Monte Carlo estimate against a quantum-accelerated sample-complexity story.",
        description:
          "The lab makes option pricing concrete while explaining where quantum amplitude-estimation ideas change the cost model rather than the payoff definition itself.",
      },
    ],
  },
];

export const ACADEMY_SUBJECT_RECORDS: AcademySubjectRecord[] = ACADEMY_SUBJECTS.map((subject) => ({
  ...subject,
  href: `/simulations/subjects/${subject.slug}`,
  simulationCount: subject.simulations.length,
}));

export const ACADEMY_SIMULATION_RECORDS: AcademySimulationRecord[] = ACADEMY_SUBJECT_RECORDS.flatMap(
  (subject) =>
    subject.simulations.map((simulation) => ({
      ...simulation,
      href: `/simulations/subjects/${subject.slug}/${simulation.slug}`,
      subjectSlug: subject.slug,
      subjectTitle: subject.title,
      subjectSummary: subject.summary,
      subjectHref: subject.href,
      subjectAccent: subject.accent,
      subjectAccentColor: subject.accentColor,
      subjectIconLabel: subject.iconLabel,
    })),
);

export const ACADEMY_SUBJECT_SLUGS = ACADEMY_SUBJECT_RECORDS.map((subject) => subject.slug);
export const ACADEMY_SIMULATION_ROUTE_LASTMOD: Record<string, string> = Object.fromEntries(
  ACADEMY_SIMULATION_RECORDS.map((simulation) => [
    `${simulation.subjectSlug}/${simulation.slug}`,
    "2026-03-30T00:00:00Z",
  ]),
);
export const ACADEMY_SUBJECT_ROUTE_LASTMOD: Record<string, string> = Object.fromEntries(
  ACADEMY_SUBJECT_RECORDS.map((subject) => [subject.slug, "2026-03-30T00:00:00Z"]),
);

export function getAcademySubjectBySlug(slug: string): AcademySubjectRecord | null {
  return ACADEMY_SUBJECT_RECORDS.find((subject) => subject.slug === slug) ?? null;
}

export function getAcademySimulationBySlug(
  subjectSlug: string,
  simulationSlug: string,
): AcademySimulationRecord | null {
  return (
    ACADEMY_SIMULATION_RECORDS.find(
      (simulation) =>
        simulation.subjectSlug === subjectSlug && simulation.slug === simulationSlug,
    ) ?? null
  );
}
