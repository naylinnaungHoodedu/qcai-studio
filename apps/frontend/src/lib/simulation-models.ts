export type BackendId = "ibm-heron" | "ionq-forte" | "simulated-ideal";
export type SimulationBucket = "QAI" | "AI4QC";
export type LaborZone =
  | "Classical preprocessing"
  | "Quantum subroutine"
  | "Classical post-processing";
export type RoutingNode = "A" | "B" | "C" | "D" | "E" | "F";
export type MemoryArchitecture = "standard" | "tiered" | "cryogenic-aware";
export type RoadmapHorizon = "1 year" | "5 years" | "10 years" | "Speculative";
export type EvidenceStrength = "Strong" | "Moderate" | "Weak" | "None";

export type NISQControls = {
  depth: number;
  gateErrorRatePct: number;
  qubitCount: number;
  backendId: BackendId;
};

export type NISQPoint = {
  layer: number;
  gateCount: number;
  fidelity: number;
};

export type NISQResult = {
  backendLabel: string;
  gateCountPerLayer: number;
  adjustedErrorRatePct: number;
  totalGateCount: number;
  thresholdCrossingLayer: number | null;
  thresholdCrossed: boolean;
  points: NISQPoint[];
};

export const NISQ_BACKENDS: Array<{
  id: BackendId;
  label: string;
  errorMultiplier: number;
  gateDensityFactor: number;
}> = [
  {
    id: "ibm-heron",
    label: "IBM Heron",
    errorMultiplier: 1,
    gateDensityFactor: 1,
  },
  {
    id: "ionq-forte",
    label: "IonQ Forte",
    errorMultiplier: 0.72,
    gateDensityFactor: 0.82,
  },
  {
    id: "simulated-ideal",
    label: "Simulated ideal",
    errorMultiplier: 0.02,
    gateDensityFactor: 0.68,
  },
];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function round(value: number, digits = 3): number {
  return Number(value.toFixed(digits));
}

export function calculateNisqSimulation({
  depth,
  gateErrorRatePct,
  qubitCount,
  backendId,
}: NISQControls): NISQResult {
  const backend = NISQ_BACKENDS.find((item) => item.id === backendId) ?? NISQ_BACKENDS[0];
  const gateCountPerLayer = Math.max(1, Math.ceil((qubitCount / 2) * backend.gateDensityFactor));
  const adjustedError = clamp((gateErrorRatePct / 100) * backend.errorMultiplier, 0.000001, 0.2);
  const points: NISQPoint[] = [];
  let thresholdCrossingLayer: number | null = null;

  for (let layer = 1; layer <= depth; layer += 1) {
    const gateCount = layer * gateCountPerLayer;
    const fidelity = clamp((1 - adjustedError) ** gateCount, 0, 1);
    if (thresholdCrossingLayer === null && fidelity < 0.85) {
      thresholdCrossingLayer = layer;
    }
    points.push({
      layer,
      gateCount,
      fidelity: round(fidelity, 4),
    });
  }

  return {
    backendLabel: backend.label,
    gateCountPerLayer,
    adjustedErrorRatePct: round(adjustedError * 100, 4),
    totalGateCount: points[points.length - 1]?.gateCount ?? 0,
    thresholdCrossingLayer,
    thresholdCrossed: thresholdCrossingLayer !== null,
    points,
  };
}

export const ABSTRACT_CASES: Array<{
  id: string;
  title: string;
  summary: string;
  label: SimulationBucket;
  rationale: string;
}> = [
  {
    id: "abs-01",
    title: "Noise-aware pulse prediction",
    summary:
      "A transformer model predicts calibration drift and gate infidelity so a superconducting device can be recalibrated before execution quality collapses.",
    label: "AI4QC",
    rationale:
      "The model improves quantum hardware operation rather than using a quantum model to solve an external AI task.",
  },
  {
    id: "abs-02",
    title: "Quantum kernel pathology screening",
    summary:
      "A hybrid kernel pipeline classifies pathology slides by feeding classical embeddings into a quantum similarity layer and a classical classifier.",
    label: "QAI",
    rationale:
      "The quantum component is being used inside the learning model for an external application task.",
  },
  {
    id: "abs-03",
    title: "RL-guided qubit routing",
    summary:
      "A reinforcement learner minimizes SWAP overhead on a heavy-hex topology by predicting routing moves for transpilation.",
    label: "AI4QC",
    rationale:
      "AI is supporting quantum compilation and device-constrained execution.",
  },
  {
    id: "abs-04",
    title: "Few-shot biomedical classifier with quantum embeddings",
    summary:
      "Few-shot episodes compare classical and quantum embedding layers before a lightweight decoder head for biomedical classification.",
    label: "QAI",
    rationale:
      "Quantum representations are used directly in the AI model that solves the downstream task.",
  },
  {
    id: "abs-05",
    title: "Adaptive readout-error mitigation",
    summary:
      "A Bayesian model updates measurement error estimates in real time and improves readout correction for NISQ experiments.",
    label: "AI4QC",
    rationale:
      "The learning component services the quantum workflow itself.",
  },
  {
    id: "abs-06",
    title: "Quantum-enhanced portfolio clustering",
    summary:
      "A hybrid clustering stack encodes market factors, uses a variational quantum subroutine, and decodes assignments classically.",
    label: "QAI",
    rationale:
      "The application target is an AI or optimization task outside the hardware stack.",
  },
  {
    id: "abs-07",
    title: "Compiler anomaly detection",
    summary:
      "Graph neural networks learn patterns in failed transpilation traces and flag unstable compiler passes for debugging.",
    label: "AI4QC",
    rationale:
      "AI is improving the compiler and execution pipeline around the quantum system.",
  },
  {
    id: "abs-08",
    title: "Quantum reservoir forecasting",
    summary:
      "A reservoir-style quantum layer is paired with a classical readout head for short-horizon industrial demand forecasting.",
    label: "QAI",
    rationale:
      "The quantum layer is part of the predictive model used for the application problem.",
  },
  {
    id: "abs-09",
    title: "Chip health prognosis via multimodal logs",
    summary:
      "A multimodal predictor combines cryostat logs and calibration history to anticipate device downtime and maintenance windows.",
    label: "AI4QC",
    rationale:
      "The AI system is maintaining the quantum hardware platform.",
  },
  {
    id: "abs-10",
    title: "Quantum kernel triage for clinical cohorts",
    summary:
      "Clinical cohort features are pushed through a quantum kernel similarity routine to improve small-data triage.",
    label: "QAI",
    rationale:
      "Quantum structure is used inside the model for the external learning task.",
  },
];

export const LABOR_TASKS: Array<{
  id: string;
  label: string;
  correctZone: LaborZone;
  rationale: string;
  zoneCosts: Record<LaborZone, number>;
}> = [
  {
    id: "normalize",
    label: "Data normalization",
    correctZone: "Classical preprocessing",
    rationale: "Normalization is classical feature preparation before any quantum encoding step.",
    zoneCosts: {
      "Classical preprocessing": 2,
      "Quantum subroutine": 8,
      "Classical post-processing": 5,
    },
  },
  {
    id: "encode",
    label: "Problem encoding",
    correctZone: "Classical preprocessing",
    rationale: "Encoding decisions are mostly classical because they shape the circuit before execution.",
    zoneCosts: {
      "Classical preprocessing": 3,
      "Quantum subroutine": 7,
      "Classical post-processing": 6,
    },
  },
  {
    id: "compile",
    label: "Gate compilation",
    correctZone: "Classical preprocessing",
    rationale: "Compilation and routing are classical control tasks around the quantum kernel.",
    zoneCosts: {
      "Classical preprocessing": 2,
      "Quantum subroutine": 9,
      "Classical post-processing": 7,
    },
  },
  {
    id: "variational",
    label: "Variational parameter optimization",
    correctZone: "Classical post-processing",
    rationale:
      "Parameter updates happen after measurements are collected and the optimizer revises the next quantum call.",
    zoneCosts: {
      "Classical preprocessing": 5,
      "Quantum subroutine": 7,
      "Classical post-processing": 3,
    },
  },
  {
    id: "measurements",
    label: "Measurement averaging",
    correctZone: "Classical post-processing",
    rationale: "Shot aggregation and expectation estimation happen after the quantum execution phase.",
    zoneCosts: {
      "Classical preprocessing": 6,
      "Quantum subroutine": 8,
      "Classical post-processing": 2,
    },
  },
  {
    id: "decode",
    label: "Output decoding",
    correctZone: "Classical post-processing",
    rationale: "Decoding maps measurement results back into the classical task space.",
    zoneCosts: {
      "Classical preprocessing": 6,
      "Quantum subroutine": 7,
      "Classical post-processing": 2,
    },
  },
];

export function evaluateLaborAssignments(assignments: Record<string, LaborZone>): {
  score: number;
  totalCost: number;
  optimalCost: number;
  costGap: number;
  correctlyPlaced: number;
} {
  const optimalCost = LABOR_TASKS.reduce((total, task) => total + task.zoneCosts[task.correctZone], 0);
  const totalCost = LABOR_TASKS.reduce((total, task) => {
    const assignedZone = assignments[task.id] ?? task.correctZone;
    return total + task.zoneCosts[assignedZone];
  }, 0);
  const correctlyPlaced = LABOR_TASKS.filter(
    (task) => (assignments[task.id] ?? task.correctZone) === task.correctZone,
  ).length;

  return {
    score: Math.round((correctlyPlaced / LABOR_TASKS.length) * 100),
    totalCost,
    optimalCost,
    costGap: totalCost - optimalCost,
    correctlyPlaced,
  };
}

export const ROUTING_COUPLING_EDGES: Array<[RoutingNode, RoutingNode]> = [
  ["A", "B"],
  ["B", "C"],
  ["C", "D"],
  ["B", "E"],
  ["E", "F"],
];

export const ROUTING_SWAP_OPTIONS = ROUTING_COUPLING_EDGES.map(([left, right]) => ({
  id: `${left}-${right}`,
  label: `${left} <-> ${right}`,
  nodes: [left, right] as const,
}));

export const INITIAL_ROUTING_MAPPING: Record<RoutingNode, string> = {
  A: "q0",
  B: "q1",
  C: "q2",
  D: "q3",
  E: "q4",
  F: "q5",
};

export const ROUTING_REQUIRED_INTERACTIONS: Array<[string, string]> = [
  ["q0", "q4"],
  ["q1", "q5"],
  ["q2", "q3"],
];

export const AI_ROUTING_SEQUENCE = ["B-E"];

function areAdjacent(left: RoutingNode, right: RoutingNode): boolean {
  return ROUTING_COUPLING_EDGES.some(
    ([edgeLeft, edgeRight]) =>
      (edgeLeft === left && edgeRight === right) || (edgeLeft === right && edgeRight === left),
  );
}

function locateLogicalQubit(mapping: Record<RoutingNode, string>, logicalQubit: string): RoutingNode {
  return (Object.entries(mapping).find(([, value]) => value === logicalQubit)?.[0] as RoutingNode) ?? "A";
}

export function applyRoutingSwap(
  mapping: Record<RoutingNode, string>,
  swapId: string,
): Record<RoutingNode, string> {
  const swap = ROUTING_SWAP_OPTIONS.find((item) => item.id === swapId);
  if (!swap) {
    return mapping;
  }
  const [left, right] = swap.nodes;
  return {
    ...mapping,
    [left]: mapping[right],
    [right]: mapping[left],
  };
}

export function evaluateRoutingMapping(
  mapping: Record<RoutingNode, string>,
  swapCount: number,
): {
  satisfied: number;
  unsatisfied: number;
  addedSwapGates: number;
  depthOverhead: number;
  missingInteractions: string[];
} {
  const satisfiedPairs = ROUTING_REQUIRED_INTERACTIONS.filter(([first, second]) => {
    const firstNode = locateLogicalQubit(mapping, first);
    const secondNode = locateLogicalQubit(mapping, second);
    return areAdjacent(firstNode, secondNode);
  });

  const missingInteractions = ROUTING_REQUIRED_INTERACTIONS.filter(
    ([first, second]) => !satisfiedPairs.some(([a, b]) => a === first && b === second),
  ).map(([first, second]) => `${first}-${second}`);

  return {
    satisfied: satisfiedPairs.length,
    unsatisfied: ROUTING_REQUIRED_INTERACTIONS.length - satisfiedPairs.length,
    addedSwapGates: swapCount * 3,
    depthOverhead: swapCount * 3 + missingInteractions.length * 2,
    missingInteractions,
  };
}

export const GRAPH_SHRINKING_OPERATIONS = [
  {
    id: "merge",
    label: "Variable merging",
    qubitReduction: 10,
    qualityLoss: 3,
    rationale: "Merge redundant variables with strongly coupled behavior.",
  },
  {
    id: "absorb",
    label: "Penalty absorption",
    qubitReduction: 7,
    qualityLoss: 2,
    rationale: "Absorb penalty terms that can be enforced classically.",
  },
  {
    id: "factor",
    label: "Subgraph factoring",
    qubitReduction: 5,
    qualityLoss: 1,
    rationale: "Factor a dense motif into a smaller classical preprocessing step.",
  },
] as const;

export function evaluateGraphShrinking(selectedIds: string[]): {
  qubits: number;
  quality: number;
  targetMet: boolean;
} {
  const selected = GRAPH_SHRINKING_OPERATIONS.filter((operation) => selectedIds.includes(operation.id));
  const qubits = selected.reduce((value, operation) => value - operation.qubitReduction, 30);
  const quality = selected.reduce((value, operation) => value - operation.qualityLoss, 100);
  return {
    qubits,
    quality,
    targetMet: qubits <= 10 && quality >= 90,
  };
}

export function buildResidualSeries(
  lambdaValue: number,
  learningRate: number,
  iterations: number,
): Array<{
  label: string;
  value: number;
  mode: "RL-tuned" | "Fixed lambda" | "Human-tuned";
}> {
  const checkpoints = [0.15, 0.35, 0.55, 0.75, 1];
  const normalizedIterations = clamp(iterations / 120, 0.2, 1.4);
  const normalizedLearningRate = clamp(learningRate / 0.3, 0.1, 2);

  return checkpoints.flatMap((checkpoint, index) => {
    const step = checkpoint * normalizedIterations * 8;
    const rlValue = clamp(
      Math.exp(-(0.42 + lambdaValue * 0.05 + normalizedLearningRate * 0.06) * step),
      0.01,
      1,
    );
    const fixedValue = clamp(Math.exp(-0.24 * step), 0.01, 1);
    const humanValue = clamp(
      Math.exp(-(0.31 + lambdaValue * 0.02) * step) * (1 + 0.05 * (index % 2)),
      0.01,
      1,
    );

    return [
      { label: `Iter ${Math.round(checkpoint * iterations)}`, value: round(rlValue, 3), mode: "RL-tuned" as const },
      {
        label: `Iter ${Math.round(checkpoint * iterations)}`,
        value: round(fixedValue, 3),
        mode: "Fixed lambda" as const,
      },
      {
        label: `Iter ${Math.round(checkpoint * iterations)}`,
        value: round(humanValue, 3),
        mode: "Human-tuned" as const,
      },
    ];
  });
}

export const HYBRID_ARCHITECTURES = [
  {
    id: "arch-1",
    title: "Clinical kernel triage",
    layers: [
      { name: "Input", contribution: "Clinical tabular features and cohort labels enter as classical measurements." },
      { name: "Classical encoder", contribution: "A compact encoder normalizes and compresses sensitive features." },
      { name: "Quantum layer", contribution: "A kernel feature map lifts the small dataset into a richer similarity space." },
      { name: "Classical decoder", contribution: "The classical head converts similarity signals into a robust classifier." },
      { name: "Output", contribution: "The model emits triage recommendations and confidence estimates." },
    ],
  },
  {
    id: "arch-2",
    title: "Few-shot biomedical embeddings",
    layers: [
      { name: "Input", contribution: "Support and query sets enter as few-shot episodes." },
      { name: "Classical encoder", contribution: "A lightweight stem maps raw observations into a stable embedding." },
      { name: "Quantum layer", contribution: "The quantum circuit enriches the low-shot embedding geometry." },
      { name: "Classical decoder", contribution: "A classical head stabilizes the final classification score." },
      { name: "Output", contribution: "Episode accuracy and class separation are measured together." },
    ],
  },
  {
    id: "arch-3",
    title: "Industrial forecasting stack",
    layers: [
      { name: "Input", contribution: "Sensor and demand features are aggregated into a short window." },
      { name: "Classical encoder", contribution: "The encoder handles scaling, denoising, and context windows." },
      { name: "Quantum layer", contribution: "A compact reservoir-style circuit perturbs the latent dynamics." },
      { name: "Classical decoder", contribution: "A decoder turns the quantum-enriched state back into a forecast." },
      { name: "Output", contribution: "Prediction error and robustness under small data are compared." },
    ],
  },
  {
    id: "arch-4",
    title: "Optimization recommender",
    layers: [
      { name: "Input", contribution: "Classical task constraints and demand forecasts enter the model." },
      { name: "Classical encoder", contribution: "The encoder prepares the combinatorial problem structure." },
      { name: "Quantum layer", contribution: "The variational solver explores a constrained candidate set." },
      { name: "Classical decoder", contribution: "The decoder filters noisy solutions and ranks tradeoffs." },
      { name: "Output", contribution: "The system outputs a prioritized schedule and solution confidence." },
    ],
  },
  {
    id: "arch-5",
    title: "Explainable molecular graph learner",
    layers: [
      { name: "Input", contribution: "Nodes and edges encode the molecular graph." },
      { name: "Classical encoder", contribution: "A graph encoder forms message-passing embeddings." },
      { name: "Quantum layer", contribution: "Quantum amplitude routines accelerate attribution sampling." },
      { name: "Classical decoder", contribution: "A classical explainer converts samples into ranked feature attributions." },
      { name: "Output", contribution: "Attribution maps surface which motifs drive the prediction." },
    ],
  },
] as const;

export function calculateKernelMetrics(dimension: number): {
  classicalAccuracy: number;
  quantumAccuracy: number;
  classicalMargin: number;
  quantumMargin: number;
  grid: Array<{ x: number; y: number; classical: number; quantum: number }>;
} {
  const scaledDimension = clamp(dimension, 2, 32);
  const classicalAccuracy = clamp(0.87 - scaledDimension * 0.006, 0.56, 0.9);
  const quantumAccuracy = clamp(0.75 + scaledDimension * 0.008, 0.7, 0.94);
  const classicalMargin = clamp(1.2 - scaledDimension * 0.03, 0.18, 1.2);
  const quantumMargin = clamp(0.42 + scaledDimension * 0.025, 0.3, 1.35);
  const grid = Array.from({ length: 49 }, (_, index) => {
    const x = (index % 7) - 3;
    const y = Math.floor(index / 7) - 3;
    const radial = x * x + y * y;
    const classicalScore = classicalMargin - radial * 0.22;
    const quantumScore = quantumMargin - Math.abs(x * y) * 0.12 + Math.sin((scaledDimension + x - y) / 6);
    return {
      x,
      y,
      classical: classicalScore,
      quantum: quantumScore,
    };
  });

  return {
    classicalAccuracy: round(classicalAccuracy * 100, 1),
    quantumAccuracy: round(quantumAccuracy * 100, 1),
    classicalMargin: round(classicalMargin, 2),
    quantumMargin: round(quantumMargin, 2),
    grid,
  };
}

export function calculateFewShotCurve(
  supportShots: number,
  embeddingDepth: number,
  headType: "linear" | "mlp" | "prototype",
): Array<{ k: number; quantum: number; classical: number }> {
  const headBonus = headType === "prototype" ? 0.03 : headType === "mlp" ? 0.015 : 0;
  const depthBonus = clamp(embeddingDepth * 0.015, 0.01, 0.08);
  return [1, 2, 5, 10].map((k) => {
    const classicalBase = 0.58 + Math.log2(k + 1) * 0.11 + supportShots * 0.008;
    const quantumBoost = k === 1 ? 0.09 : k <= 2 ? 0.06 : k <= 5 ? 0.03 : 0.005;
    return {
      k,
      classical: round(clamp(classicalBase * 100, 45, 92), 1),
      quantum: round(clamp((classicalBase + quantumBoost + depthBonus + headBonus) * 100, 48, 95), 1),
    };
  });
}

export function calculateCompressionMetrics(
  quantumParameterCount: number,
  signalType: "image" | "signal",
): {
  classicalRatio: number;
  quantumRatio: number;
  classicalPsnr: number;
  quantumPsnr: number;
  residualFocus: string;
} {
  const normalizedParams = clamp(quantumParameterCount / 100, 0.08, 1);
  const imageBias = signalType === "image" ? 1 : 0.8;
  const classicalRatio = round(18 - normalizedParams * 4 * imageBias, 1);
  const quantumRatio = round(24 - normalizedParams * 6 * imageBias, 1);
  const classicalPsnr = round(26 + normalizedParams * 5 * imageBias, 1);
  const quantumPsnr = round(29 + normalizedParams * 7 * imageBias, 1);
  const residualFocus =
    signalType === "image"
      ? "quINR retains higher-frequency edges and textures more efficiently at the same parameter count."
      : "quINR retains oscillatory spectral components more efficiently at the same parameter count.";

  return {
    classicalRatio,
    quantumRatio,
    classicalPsnr,
    quantumPsnr,
    residualFocus,
  };
}

export function calculateQgshapMetrics(nodeCount: number, sampleBudget: number): {
  exactCost: number;
  sampledCost: number;
  quantumCost: number;
  speedupVsSampled: number;
} {
  const exactCost = 2 ** clamp(nodeCount, 4, 12);
  const sampledCost = clamp(sampleBudget, 64, 4096);
  const quantumCost = Math.ceil(Math.sqrt(sampledCost) * 4);
  return {
    exactCost,
    sampledCost,
    quantumCost,
    speedupVsSampled: round(sampledCost / quantumCost, 1),
  };
}

export function calculateSolverRace(problemSize: number): Array<{
  name: string;
  runtimeMs: number;
  objectiveGap: number;
  costUsd: number;
  progressPercent: number;
}> {
  const normalizedSize = clamp(problemSize, 12, 120);
  return [
    {
      name: "Classical brute force",
      runtimeMs: Math.round(40 + normalizedSize ** 1.7),
      objectiveGap: round(clamp(24 - normalizedSize * 0.08, 8, 24), 1),
      costUsd: round(0.04 + normalizedSize * 0.001, 2),
      progressPercent: round(clamp(98 - normalizedSize * 0.55, 22, 98), 1),
    },
    {
      name: "Simulated annealing",
      runtimeMs: Math.round(28 + normalizedSize ** 1.25),
      objectiveGap: round(clamp(14 - normalizedSize * 0.05, 3, 14), 1),
      costUsd: round(0.09 + normalizedSize * 0.002, 2),
      progressPercent: round(clamp(88 - normalizedSize * 0.2, 52, 88), 1),
    },
    {
      name: "QUBO / D-Wave-style",
      runtimeMs: Math.round(55 + normalizedSize ** 1.05),
      objectiveGap: round(clamp(18 - normalizedSize * 0.12, 1, 18), 1),
      costUsd: round(0.25 + normalizedSize * 0.012, 2),
      progressPercent: round(clamp(62 + normalizedSize * 0.25, 62, 96), 1),
    },
  ];
}

export const PQC_SERVICES: Array<{
  id: string;
  name: string;
  crypto: "RSA-2048" | "ECC-256" | "AES-128" | "AES-256" | "Signature";
  correctAction: "Hold" | "Upgrade to AES-256" | "Migrate to ML-KEM" | "Migrate to ML-DSA" | "Migrate to SLH-DSA";
  rationale: string;
}> = [
  {
    id: "svc-01",
    name: "Customer portal VPN",
    crypto: "RSA-2048",
    correctAction: "Migrate to ML-KEM",
    rationale: "Key encapsulation is the urgent migration path for RSA transport security.",
  },
  {
    id: "svc-02",
    name: "Warehouse telemetry gateway",
    crypto: "ECC-256",
    correctAction: "Migrate to ML-DSA",
    rationale: "Elliptic-curve signatures require PQ signature replacement.",
  },
  {
    id: "svc-03",
    name: "Data lake object encryption",
    crypto: "AES-256",
    correctAction: "Hold",
    rationale: "AES-256 is already quantum-resistant at the currently taught threat model.",
  },
  {
    id: "svc-04",
    name: "Legacy partner SFTP",
    crypto: "RSA-2048",
    correctAction: "Migrate to ML-KEM",
    rationale: "Transport keys remain vulnerable to Shor-style public-key attacks.",
  },
  {
    id: "svc-05",
    name: "Edge device firmware signing",
    crypto: "Signature",
    correctAction: "Migrate to SLH-DSA",
    rationale: "Signature systems need a PQ signature path, not a symmetric-key change.",
  },
  {
    id: "svc-06",
    name: "Clinical archive encryption",
    crypto: "AES-128",
    correctAction: "Upgrade to AES-256",
    rationale: "This is a symmetric-key hygiene upgrade, not a PQC swap.",
  },
  {
    id: "svc-07",
    name: "Identity federation tokens",
    crypto: "ECC-256",
    correctAction: "Migrate to ML-DSA",
    rationale: "Signature-backed federation must leave ECC for a PQ signature scheme.",
  },
  {
    id: "svc-08",
    name: "Internal message queue",
    crypto: "AES-256",
    correctAction: "Hold",
    rationale: "No PQ migration is required for the symmetric cipher itself.",
  },
  {
    id: "svc-09",
    name: "Remote maintenance tunnel",
    crypto: "RSA-2048",
    correctAction: "Migrate to ML-KEM",
    rationale: "Key exchange still depends on vulnerable public-key material.",
  },
  {
    id: "svc-10",
    name: "Plant historian backups",
    crypto: "AES-128",
    correctAction: "Upgrade to AES-256",
    rationale: "This is a symmetric-key hygiene upgrade, not a PQC swap.",
  },
  {
    id: "svc-11",
    name: "Device provisioning certificates",
    crypto: "Signature",
    correctAction: "Migrate to SLH-DSA",
    rationale: "Certificate signatures need PQ-safe signing primitives.",
  },
  {
    id: "svc-12",
    name: "Supplier API signing",
    crypto: "ECC-256",
    correctAction: "Migrate to ML-DSA",
    rationale: "The risk is in ECC signing, not the symmetric payload cipher.",
  },
];

export function evaluatePqcPlan(actions: Record<string, string>): {
  correctCount: number;
  incorrectCount: number;
  criticalRemaining: number;
  threatPercent: number;
} {
  let correctCount = 0;
  let criticalRemaining = 0;

  for (const service of PQC_SERVICES) {
    const selected = actions[service.id];
    if (selected === service.correctAction) {
      correctCount += 1;
    } else if (service.crypto === "RSA-2048" || service.crypto === "ECC-256" || service.crypto === "Signature") {
      criticalRemaining += 1;
    }
  }

  return {
    correctCount,
    incorrectCount: PQC_SERVICES.length - correctCount,
    criticalRemaining,
    threatPercent: Math.round((criticalRemaining / PQC_SERVICES.length) * 100),
  };
}

export const VERTICAL_CONNECTIONS = [
  {
    id: "vertical-01",
    vertical: "Logistics",
    application: "Routing and fleet scheduling",
    maturity: "Pilot",
    horizon: "3-5 years",
    passage:
      "Optimization-centric verticals are closest to near-term QC+AI evaluation because constrained scheduling maps cleanly into hybrid reformulation workflows.",
  },
  {
    id: "vertical-02",
    vertical: "Biomedicine",
    application: "Small-data classification",
    maturity: "Research",
    horizon: "1-3 years",
    passage:
      "Clinical and biomedical kernels are strongest when data volume is small and representation quality matters more than scale.",
  },
  {
    id: "vertical-03",
    vertical: "Energy",
    application: "Grid optimization",
    maturity: "Pilot",
    horizon: "3-5 years",
    passage:
      "Energy applications favor hybrid optimization and routing because operational constraints are already classically structured.",
  },
  {
    id: "vertical-04",
    vertical: "Materials",
    application: "Molecular property inference",
    maturity: "Research",
    horizon: "5-10 years",
    passage:
      "High-value science applications remain evidence-rich but are still bounded by hardware realism and narrow problem sizes.",
  },
  {
    id: "vertical-05",
    vertical: "Cybersecurity",
    application: "Post-quantum migration planning",
    maturity: "Operational",
    horizon: "Now",
    passage:
      "The most immediate commercial impact is defensive preparation rather than waiting for full fault-tolerant advantage.",
  },
  {
    id: "vertical-06",
    vertical: "Manufacturing",
    application: "Predictive maintenance and scheduling",
    maturity: "Pilot",
    horizon: "1-5 years",
    passage:
      "Hybrid QC+AI stacks are plausible where maintenance forecasting and constrained scheduling interact.",
  },
] as const;

export function calculateThermodynamicMetrics(
  classicalAllocation: number,
  qpuShots: number,
  memoryArchitecture: MemoryArchitecture,
): {
  energyJoules: number;
  memoryCost: number;
  quality: number;
  landauerRatio: number;
} {
  const memoryFactor =
    memoryArchitecture === "cryogenic-aware" ? 1.08 : memoryArchitecture === "tiered" ? 1.16 : 1.32;
  const energyJoules = round((classicalAllocation * 0.18 + qpuShots * 0.0045) * memoryFactor, 3);
  const memoryCost = round((classicalAllocation * 0.6 + qpuShots * 0.03) * memoryFactor, 2);
  const quality = round(
    clamp(58 + classicalAllocation * 0.22 + Math.log1p(qpuShots) * 6 - (memoryFactor - 1) * 12, 45, 99),
    1,
  );
  const landauerRatio = round(energyJoules / 0.000000000000000000004, 2);

  return {
    energyJoules,
    memoryCost,
    quality,
    landauerRatio,
  };
}

export const ROADMAP_CLAIMS: Array<{
  id: string;
  claim: string;
  correctHorizon: RoadmapHorizon;
  correctEvidence: EvidenceStrength;
  rationale: string;
}> = [
  {
    id: "claim-01",
    claim: "AI-assisted qubit routing will keep improving near-term compilation quality on sparse topologies.",
    correctHorizon: "1 year",
    correctEvidence: "Strong",
    rationale: "Routing support is already evidenced in the near-term hardware workflow.",
  },
  {
    id: "claim-02",
    claim: "Quantum kernels may retain niche value on small, structured biomedical datasets.",
    correctHorizon: "5 years",
    correctEvidence: "Moderate",
    rationale: "The signal is real but task-dependent and far from universal advantage.",
  },
  {
    id: "claim-03",
    claim: "Fault-tolerant quantum AI will dominate large foundation-model training this decade.",
    correctHorizon: "Speculative",
    correctEvidence: "Weak",
    rationale: "This is still a speculative leap beyond current hardware and evidence.",
  },
  {
    id: "claim-04",
    claim: "Post-quantum migration planning is a current operational priority for enterprises.",
    correctHorizon: "1 year",
    correctEvidence: "Strong",
    rationale: "Migration work is already underway today and is not a distant forecast.",
  },
  {
    id: "claim-05",
    claim: "Quantum-accelerated explainability may reduce sampling cost before full hardware advantage arrives.",
    correctHorizon: "5 years",
    correctEvidence: "Moderate",
    rationale: "The idea is promising but still bounded by proof-of-concept scale.",
  },
  {
    id: "claim-06",
    claim: "Energy-aware QC+AI scheduling should be part of near-term system design discussions.",
    correctHorizon: "5 years",
    correctEvidence: "Moderate",
    rationale: "Thermodynamic cost reasoning is relevant now even if exact optimization remains immature.",
  },
];

export function evaluateRoadmapPlacements(
  placements: Record<string, { horizon: RoadmapHorizon; evidence: EvidenceStrength }>,
): {
  correct: number;
  total: number;
} {
  const correct = ROADMAP_CLAIMS.filter((claim) => {
    const placement = placements[claim.id];
    return placement?.horizon === claim.correctHorizon && placement?.evidence === claim.correctEvidence;
  }).length;
  return {
    correct,
    total: ROADMAP_CLAIMS.length,
  };
}
