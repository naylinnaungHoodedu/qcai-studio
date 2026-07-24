// Plain-language glossary for the QC+AI course.
//
// The platform's biggest first-visit friction is jargon that appears before any
// plain-language framing (NISQ, QUBO, VQC, QAI vs AI4QC, ...). This module gives
// every heavy term a short, honest, non-specialist definition so the UI can
// explain terms on demand and lead newcomers in gently.

export type GlossaryEntry = {
  term: string;
  // A one-line, plain-English definition. No new jargon inside a definition.
  plain: string;
};

// The handful of ideas a newcomer must grasp to make sense of the whole course.
// Rendered as a friendly "New to QC+AI?" explainer on the home page.
export const CORE_CONCEPTS: readonly GlossaryEntry[] = [
  {
    term: "QC+AI",
    plain:
      "Quantum computing and artificial intelligence used together — this course is about where combining them actually helps today.",
  },
  {
    term: "NISQ",
    plain:
      "Today's quantum hardware: small, noisy, and error-prone. It shapes what is realistic to build right now, so the course keeps it front and center.",
  },
  {
    term: "Qubit",
    plain:
      "The quantum version of a bit. Qubits are scarce and fragile on current machines, which is why efficiency matters so much.",
  },
  {
    term: "Hybrid quantum-classical",
    plain:
      "Designs where a normal (classical) computer does most of the work and a small quantum step is used only where it genuinely pays off.",
  },
] as const;

// The full term bank used by the inline <GlossaryTerm> helper. Keep definitions
// short and jargon-free; add terms as new lesson copy introduces them.
export const GLOSSARY: Record<string, string> = {
  "QC+AI":
    "Quantum computing and artificial intelligence used together.",
  NISQ:
    "Noisy Intermediate-Scale Quantum — today's small, noisy, error-prone quantum hardware.",
  Qubit:
    "The quantum version of a bit; scarce and fragile on current hardware.",
  "Hybrid quantum-classical":
    "A design where a classical computer does most of the work and a small quantum step is added only where it helps.",
  QAI:
    "Quantum-enhanced AI — using a quantum step to improve an AI model.",
  AI4QC:
    "AI for quantum computing — using AI/ML to make quantum hardware and circuits work better.",
  VQC:
    "Variational Quantum Circuit — a small, trainable quantum circuit whose settings are tuned like a model's weights.",
  VQA:
    "Variational Quantum Algorithm — an algorithm that trains a quantum circuit by adjusting its parameters.",
  QUBO:
    "Quadratic Unconstrained Binary Optimization — a way to rewrite a hard decision problem so a quantum or classical optimizer can attack it.",
  Ansatz:
    "The chosen shape/structure of a quantum circuit before its parameters are tuned.",
  "Barren plateau":
    "A training failure where the signal used to improve a quantum circuit becomes vanishingly small.",
  "Few-shot":
    "Learning to do a task well from only a handful of examples.",
  QViT:
    "Quantum Vision Transformer — a vision model with a quantum-enhanced component.",
  GNN:
    "Graph Neural Network — a model that learns over graph-structured data (nodes and edges).",
  // Aliases and extra terms so the acronym tags on module cards get plain-language hovers.
  VQCs:
    "Variational Quantum Circuits — small, trainable quantum circuits tuned like a model's weights.",
  "Barren plateaus":
    "A training failure where the signal used to improve a quantum circuit becomes vanishingly small.",
  Shots:
    "How many times a quantum circuit is run and measured to estimate a result. More shots means less noise but more cost.",
  "Parameter shift":
    "A rule for computing gradients of a quantum circuit so it can be trained.",
  "Pulse control":
    "Programming quantum hardware at the level of its physical control pulses, for finer performance.",
  "RL-Q-ALM":
    "A hybrid method that uses reinforcement learning to guide quantum optimization for routing and logistics.",
  QGSHAP:
    "A technique for explaining a model's decisions using quantum amplitude methods (quantum Shapley-style explainability).",
  "CV-QNN":
    "Continuous-Variable Quantum Neural Network — a quantum model that uses continuous states, not just 0/1.",
  MLIR:
    "Multi-Level Intermediate Representation — a compiler framework used to build quantum software toolchains.",
  "Graph shrinking":
    "Reducing a large graph/problem to a smaller one a constrained quantum device can handle.",
};

export function getGlossaryDefinition(term: string): string | undefined {
  return GLOSSARY[term];
}
