"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import {
  ABSTRACT_CASES,
  AI_ROUTING_SEQUENCE,
  GRAPH_SHRINKING_OPERATIONS,
  HYBRID_ARCHITECTURES,
  INITIAL_ROUTING_MAPPING,
  LABOR_TASKS,
  NISQ_BACKENDS,
  PQC_SERVICES,
  ROADMAP_CLAIMS,
  ROUTING_REQUIRED_INTERACTIONS,
  ROUTING_SWAP_OPTIONS,
  VERTICAL_CONNECTIONS,
  applyRoutingSwap,
  buildResidualSeries,
  calculateCompressionMetrics,
  calculateFewShotCurve,
  calculateKernelMetrics,
  calculateNisqSimulation,
  calculateQgshapMetrics,
  calculateSolverRace,
  calculateThermodynamicMetrics,
  evaluateGraphShrinking,
  evaluateLaborAssignments,
  evaluatePqcPlan,
  evaluateRoadmapPlacements,
  evaluateRoutingMapping,
} from "@/lib/simulation-models";
import type {
  BackendId,
  EvidenceStrength,
  LaborZone,
  MemoryArchitecture,
  RoadmapHorizon,
  SimulationBucket,
} from "@/lib/simulation-models";
import type { SimulationConcept, SimulationModule } from "@/lib/simulations";

function MetricTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <article className="simulation-metric-tile">
      <span className="eyebrow">{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function ChartBars({
  values,
  maxValue,
  formatter,
}: {
  values: Array<{ label: string; value: number }>;
  maxValue: number;
  formatter?: (value: number) => string;
}) {
  return (
    <div className="simulation-chart-row">
      {values.map((item) => {
        const height = Math.max((item.value / maxValue) * 100, 6);
        return (
          <div className="simulation-bar-column" key={item.label}>
            <div className="simulation-bar-track">
              <span style={{ height: `${height}%` }} />
            </div>
            <strong>{formatter ? formatter(item.value) : item.value}</strong>
            <p>{item.label}</p>
          </div>
        );
      })}
    </div>
  );
}

function LabShell({
  title,
  summary,
  controls,
  outputs,
}: {
  title: string;
  summary: string;
  controls: ReactNode;
  outputs: ReactNode;
}) {
  return (
    <div className="simulation-lab">
      <div className="simulation-lab-header">
        <div>
          <p className="eyebrow">Browser-playable lab</p>
          <h4>{title}</h4>
        </div>
        <p>{summary}</p>
      </div>
      <div className="simulation-lab-grid">
        <section className="simulation-lab-panel">
          <p className="eyebrow">Controls</p>
          {controls}
        </section>
        <section className="simulation-lab-panel" aria-live="polite">
          <p className="eyebrow">Outputs</p>
          {outputs}
        </section>
      </div>
    </div>
  );
}

function NISQFidelityLab() {
  const [depth, setDepth] = useState(28);
  const [gateErrorRatePct, setGateErrorRatePct] = useState(0.8);
  const [qubitCount, setQubitCount] = useState(10);
  const [backendId, setBackendId] = useState<BackendId>("ibm-heron");
  const result = calculateNisqSimulation({
    depth,
    gateErrorRatePct,
    qubitCount,
    backendId,
  });
  const sampledPoints = result.points.filter((_, index) => index % Math.max(Math.floor(result.points.length / 10), 1) === 0);

  return (
    <LabShell
      title="The NISQ Fidelity Cliff"
      summary="Conservative upper-bound model with total noisy gate count G per layer, not depth times qubits."
      controls={
        <div className="simulation-control-grid">
          <label>
            Circuit depth: {depth}
            <input max={100} min={1} onChange={(event) => setDepth(Number(event.target.value))} type="range" value={depth} />
          </label>
          <label>
            Gate error rate: {gateErrorRatePct.toFixed(3)}%
            <input
              max={5}
              min={0.001}
              onChange={(event) => setGateErrorRatePct(Number(event.target.value))}
              step={0.001}
              type="range"
              value={gateErrorRatePct}
            />
          </label>
          <label>
            Qubit count
            <select onChange={(event) => setQubitCount(Number(event.target.value))} value={qubitCount}>
              {[5, 10, 20, 50].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Backend
            <select onChange={(event) => setBackendId(event.target.value as BackendId)} value={backendId}>
              {NISQ_BACKENDS.map((backend) => (
                <option key={backend.id} value={backend.id}>
                  {backend.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile
              detail="Maximum gate density per layer assumption."
              label="Gate count / layer"
              value={String(result.gateCountPerLayer)}
            />
            <MetricTile
              detail="Backend-adjusted epsilon."
              label="Adjusted error"
              value={`${result.adjustedErrorRatePct}%`}
            />
            <MetricTile
              detail="Illustrative teaching threshold at 0.85 fidelity."
              label="Threshold"
              value={result.thresholdCrossingLayer ? `Layer ${result.thresholdCrossingLayer}` : "Above 0.85"}
            />
          </div>
          <ChartBars
            formatter={(value) => value.toFixed(2)}
            maxValue={1}
            values={sampledPoints.map((point) => ({
              label: `L${point.layer}`,
              value: point.fidelity,
            }))}
          />
          <p className="simulation-status-copy">
            Final modeled fidelity is {result.points[result.points.length - 1]?.fidelity.toFixed(4)} after {result.totalGateCount} total noisy gates on {result.backendLabel}.
          </p>
        </div>
      }
    />
  );
}

function DecisionTreeLab() {
  const [assignments, setAssignments] = useState<Record<string, SimulationBucket | undefined>>({});
  const correct = ABSTRACT_CASES.filter((item) => assignments[item.id] === item.label).length;

  return (
    <LabShell
      title="QAI vs. AI4QC Decision Tree"
      summary="Classify proceeding-style abstracts by whether quantum methods are serving AI tasks or AI is supporting quantum hardware workflows."
      controls={
        <div className="simulation-card-grid compact">
          {ABSTRACT_CASES.map((item) => (
            <article className="simulation-mini-card" key={item.id}>
              <strong>{item.title}</strong>
              <p>{item.summary}</p>
              <div className="simulation-choice-row">
                {(["QAI", "AI4QC"] as const).map((choice) => (
                  <button
                    className={`secondary-button ${assignments[item.id] === choice ? "is-selected" : ""}`}
                    key={choice}
                    onClick={() =>
                      setAssignments((current) => ({
                        ...current,
                        [item.id]: choice,
                      }))
                    }
                    type="button"
                  >
                    {choice}
                  </button>
                ))}
              </div>
              {assignments[item.id] ? (
                <p className={assignments[item.id] === item.label ? "simulation-success" : "simulation-warning"}>
                  Correct label: {item.label}. {item.rationale}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile
              detail="Each classification reveals the reasoning immediately."
              label="Correct"
              value={`${correct} / ${ABSTRACT_CASES.length}`}
            />
            <MetricTile
              detail="Use the rationale to distinguish application-facing versus hardware-facing work."
              label="Progress"
              value={`${Math.round((correct / ABSTRACT_CASES.length) * 100)}%`}
            />
          </div>
          <p className="simulation-status-copy">
            The key distinction is operational: QAI uses quantum machinery inside the model for an external task, while AI4QC uses AI to improve quantum devices, routing, calibration, or execution quality.
          </p>
        </div>
      }
    />
  );
}

function LaborSplitLab() {
  const [assignments, setAssignments] = useState<Record<string, LaborZone>>({
    normalize: "Classical preprocessing",
    encode: "Quantum subroutine",
    compile: "Quantum subroutine",
    variational: "Classical post-processing",
    measurements: "Classical preprocessing",
    decode: "Classical post-processing",
  });
  const result = evaluateLaborAssignments(assignments);

  return (
    <LabShell
      title="Hybrid Labor Split Visualizer"
      summary="Assign each workflow task to the stage where it belongs and compare orchestration cost against the optimal split."
      controls={
        <div className="simulation-detail-list">
          {LABOR_TASKS.map((task) => (
            <div className="simulation-detail-item" key={task.id}>
              <strong>{task.label}</strong>
              <select
                onChange={(event) =>
                  setAssignments((current) => ({
                    ...current,
                    [task.id]: event.target.value as LaborZone,
                  }))
                }
                value={assignments[task.id]}
              >
                <option value="Classical preprocessing">Classical preprocessing</option>
                <option value="Quantum subroutine">Quantum subroutine</option>
                <option value="Classical post-processing">Classical post-processing</option>
              </select>
              <p>{task.rationale}</p>
            </div>
          ))}
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Tasks placed in the correct stage." label="Correctly placed" value={`${result.correctlyPlaced} / ${LABOR_TASKS.length}`} />
            <MetricTile detail="Sum of orchestration cost across all stage choices." label="Workflow cost" value={`${result.totalCost} units`} />
            <MetricTile detail="Distance from the best-known labor split." label="Cost gap" value={`${result.costGap >= 0 ? "+" : ""}${result.costGap} units`} />
          </div>
          <p className="simulation-status-copy">
            Optimal hybrid systems keep encoding and compilation classical, treat the quantum routine as a narrow kernel, and move averaging plus optimization back into classical post-processing.
          </p>
        </div>
      }
    />
  );
}

function RoutingSandboxLab() {
  const [mapping, setMapping] = useState(INITIAL_ROUTING_MAPPING);
  const [swapHistory, setSwapHistory] = useState<string[]>([]);
  const result = evaluateRoutingMapping(mapping, swapHistory.length);

  function runSwap(swapId: string) {
    setMapping((current) => applyRoutingSwap(current, swapId));
    setSwapHistory((current) => [...current, swapId]);
  }

  function reset() {
    setMapping(INITIAL_ROUTING_MAPPING);
    setSwapHistory([]);
  }

  function runAiRoute() {
    let nextMapping = INITIAL_ROUTING_MAPPING;
    for (const swapId of AI_ROUTING_SEQUENCE) {
      nextMapping = applyRoutingSwap(nextMapping, swapId);
    }
    setMapping(nextMapping);
    setSwapHistory(AI_ROUTING_SEQUENCE);
  }

  return (
    <LabShell
      title="Qubit Routing Sandbox"
      summary="Manual SWAP insertion shows how sparse coupling creates depth overhead; the AI router reveals a tighter path on the same topology."
      controls={
        <div className="stack">
          <div className="simulation-routing-grid">
            {Object.entries(mapping).map(([node, logical]) => (
              <article className="simulation-routing-node" key={node}>
                <span className="eyebrow">Physical {node}</span>
                <strong>{logical}</strong>
              </article>
            ))}
          </div>
          <div className="button-row">
            {ROUTING_SWAP_OPTIONS.map((option) => (
              <button className="secondary-button" key={option.id} onClick={() => runSwap(option.id)} type="button">
                {option.label}
              </button>
            ))}
          </div>
          <div className="button-row">
            <button className="primary-button" onClick={runAiRoute} type="button">
              Run AI router
            </button>
            <button className="secondary-button" onClick={reset} type="button">
              Reset mapping
            </button>
          </div>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Logical interaction pairs already adjacent on the coupling graph." label="Satisfied pairs" value={`${result.satisfied} / ${ROUTING_REQUIRED_INTERACTIONS.length}`} />
            <MetricTile detail="Each SWAP is counted as three added gate operations." label="Added SWAP gates" value={String(result.addedSwapGates)} />
            <MetricTile detail="Illustrative depth penalty from routing and unresolved interactions." label="Depth overhead" value={`+${result.depthOverhead}`} />
          </div>
          <p className="simulation-status-copy">
            Missing interactions: {result.missingInteractions.length ? result.missingInteractions.join(", ") : "none"}.
          </p>
          <p className="muted">
            The one-step AI route swaps B and E, satisfying all three required interactions on this IBM Heron-style sparse graph.
          </p>
        </div>
      }
    />
  );
}

function GraphShrinkingLab() {
  const [selected, setSelected] = useState<string[]>(["merge"]);
  const result = evaluateGraphShrinking(selected);

  return (
    <LabShell
      title="Graph Shrinking Workshop"
      summary="Apply reformulation moves until the QUBO fits the qubit budget while preserving acceptable solution quality."
      controls={
        <div className="simulation-detail-list">
          {GRAPH_SHRINKING_OPERATIONS.map((operation) => {
            const active = selected.includes(operation.id);
            return (
              <button
                className={`simulation-detail-item simulation-toggle ${active ? "is-selected" : ""}`}
                key={operation.id}
                onClick={() =>
                  setSelected((current) =>
                    current.includes(operation.id)
                      ? current.filter((item) => item !== operation.id)
                      : [...current, operation.id],
                  )
                }
                type="button"
              >
                <strong>{operation.label}</strong>
                <p>{operation.rationale}</p>
                <p className="muted">
                  -{operation.qubitReduction} qubits, -{operation.qualityLoss}% quality
                </p>
              </button>
            );
          })}
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Target is under 10 qubits." label="Encoded qubits" value={String(result.qubits)} />
            <MetricTile detail="Target is above 90 percent solution quality." label="Estimated quality" value={`${result.quality}%`} />
            <MetricTile detail="Both constraints must hold at once." label="Goal state" value={result.targetMet ? "Target met" : "Still off target"} />
          </div>
          <p className="simulation-status-copy">
            Variable merging, penalty absorption, and subgraph factoring together show how much classical reformulation work is needed before a small quantum device becomes relevant.
          </p>
        </div>
      }
    />
  );
}

function ResidualLab() {
  const [lambdaValue, setLambdaValue] = useState(1.6);
  const [learningRate, setLearningRate] = useState(0.12);
  const [iterations, setIterations] = useState(80);
  const series = buildResidualSeries(lambdaValue, learningRate, iterations);
  const modes = ["RL-tuned", "Fixed lambda", "Human-tuned"] as const;

  return (
    <LabShell
      title="RL-Tuned Augmented Lagrangian Explorer"
      summary="Compare primal and dual residual collapse under RL-tuned, fixed, and human-tuned lambda strategies."
      controls={
        <div className="simulation-control-grid">
          <label>
            Lambda: {lambdaValue.toFixed(2)}
            <input max={3} min={0.4} onChange={(event) => setLambdaValue(Number(event.target.value))} step={0.05} type="range" value={lambdaValue} />
          </label>
          <label>
            Learning rate: {learningRate.toFixed(2)}
            <input max={0.3} min={0.01} onChange={(event) => setLearningRate(Number(event.target.value))} step={0.01} type="range" value={learningRate} />
          </label>
          <label>
            ADMM iterations: {iterations}
            <input max={120} min={20} onChange={(event) => setIterations(Number(event.target.value))} step={5} type="range" value={iterations} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          {modes.map((mode) => (
            <div key={mode}>
              <strong>{mode}</strong>
              <ChartBars
                formatter={(value) => value.toFixed(2)}
                maxValue={1}
                values={series.filter((item) => item.mode === mode).map((item) => ({ label: item.label, value: item.value }))}
              />
            </div>
          ))}
          <p className="simulation-status-copy">
            The RL-tuned policy should settle faster because it adapts lambda and learning dynamics together instead of leaving the penalty schedule static.
          </p>
        </div>
      }
    />
  );
}

function ArchitectureDissectorLab() {
  const [selectedArchitectureId, setSelectedArchitectureId] = useState<string>(
    HYBRID_ARCHITECTURES[0].id,
  );
  const [selectedLayer, setSelectedLayer] = useState<string>(
    HYBRID_ARCHITECTURES[0].layers[2].name,
  );
  const architecture =
    HYBRID_ARCHITECTURES.find((item) => item.id === selectedArchitectureId) ?? HYBRID_ARCHITECTURES[0];
  const layer = architecture.layers.find((item) => item.name === selectedLayer) ?? architecture.layers[0];

  return (
    <LabShell
      title="Hybrid Architecture Dissector"
      summary="Inspect how the classical encoder, quantum layer, and classical decoder cooperate instead of pretending the quantum component replaces the whole model."
      controls={
        <div className="stack">
          <div className="simulation-choice-row">
            {HYBRID_ARCHITECTURES.map((item) => (
              <button
                className={`secondary-button ${selectedArchitectureId === item.id ? "is-selected" : ""}`}
                key={item.id}
                onClick={() => {
                  setSelectedArchitectureId(item.id);
                  setSelectedLayer(item.layers[0].name);
                }}
                type="button"
              >
                {item.title}
              </button>
            ))}
          </div>
          <div className="simulation-choice-row">
            {architecture.layers.map((item) => (
              <button
                className={`secondary-button ${selectedLayer === item.name ? "is-selected" : ""}`}
                key={item.name}
                onClick={() => setSelectedLayer(item.name)}
                type="button"
              >
                {item.name}
              </button>
            ))}
          </div>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="The selected paper-derived pipeline." label="Architecture" value={architecture.title} />
            <MetricTile detail="The active layer under inspection." label="Layer" value={layer.name} />
          </div>
          <p className="simulation-status-copy">{layer.contribution}</p>
          <p className="muted">
            Side-by-side comparison matters because each architecture keeps the quantum segment narrow, task-specific, and heavily scaffolded by classical infrastructure.
          </p>
        </div>
      }
    />
  );
}

function KernelComparatorLab() {
  const [dimension, setDimension] = useState(12);
  const metrics = calculateKernelMetrics(dimension);

  return (
    <LabShell
      title="Quantum Kernel vs. Classical Kernel Comparator"
      summary="Scale the feature dimension and compare decision-surface behavior between an RBF SVM and a quantum-kernel SVM."
      controls={
        <div className="simulation-control-grid">
          <label>
            Feature dimension: {dimension}
            <input max={32} min={2} onChange={(event) => setDimension(Number(event.target.value))} type="range" value={dimension} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Validation accuracy under the modeled classical kernel." label="Classical accuracy" value={`${metrics.classicalAccuracy}%`} />
            <MetricTile detail="Validation accuracy under the modeled quantum kernel." label="Quantum accuracy" value={`${metrics.quantumAccuracy}%`} />
            <MetricTile detail="A wider margin indicates more separation in this teaching proxy." label="Quantum margin" value={metrics.quantumMargin.toFixed(2)} />
          </div>
          <div className="simulation-boundary-grid">
            {metrics.grid.map((cell) => (
              <div className="simulation-boundary-pair" key={`${cell.x}-${cell.y}`}>
                <span
                  className={`simulation-boundary-cell ${cell.classical >= 0 ? "positive" : "negative"}`}
                  title={`Classical score ${cell.classical.toFixed(2)}`}
                />
                <span
                  className={`simulation-boundary-cell ${cell.quantum >= 0 ? "positive" : "negative"}`}
                  title={`Quantum score ${cell.quantum.toFixed(2)}`}
                />
              </div>
            ))}
          </div>
          <p className="muted">Left square in each pair: classical boundary. Right square: quantum boundary.</p>
        </div>
      }
    />
  );
}

function FewShotLab() {
  const [supportShots, setSupportShots] = useState(3);
  const [embeddingDepth, setEmbeddingDepth] = useState(2);
  const [headType, setHeadType] = useState<"linear" | "mlp" | "prototype">("prototype");
  const curve = calculateFewShotCurve(supportShots, embeddingDepth, headType);

  return (
    <LabShell
      title="Few-Shot Learning Episode Builder"
      summary="Tune the support set, embedding depth, and decoder head to see where quantum embeddings help and where parity returns."
      controls={
        <div className="simulation-control-grid">
          <label>
            Support set K: {supportShots}
            <input max={10} min={1} onChange={(event) => setSupportShots(Number(event.target.value))} type="range" value={supportShots} />
          </label>
          <label>
            Quantum embedding depth: {embeddingDepth}
            <input max={5} min={1} onChange={(event) => setEmbeddingDepth(Number(event.target.value))} type="range" value={embeddingDepth} />
          </label>
          <label>
            Classical head
            <select onChange={(event) => setHeadType(event.target.value as "linear" | "mlp" | "prototype")} value={headType}>
              <option value="linear">Linear</option>
              <option value="mlp">MLP</option>
              <option value="prototype">Prototype</option>
            </select>
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <ChartBars
            formatter={(value) => `${value.toFixed(1)}%`}
            maxValue={100}
            values={curve.map((item) => ({
              label: `K=${item.k} quantum`,
              value: item.quantum,
            }))}
          />
          <div className="simulation-table">
            {curve.map((item) => (
              <div className="simulation-table-row" key={item.k}>
                <span>K={item.k}</span>
                <span>Quantum {item.quantum}%</span>
                <span>Classical {item.classical}%</span>
              </div>
            ))}
          </div>
          <p className="simulation-status-copy">
            The modeled advantage is strongest at K=1 and K=2, then compresses toward classical parity as support examples become abundant.
          </p>
        </div>
      }
    />
  );
}

function CompressionLab() {
  const [quantumParameterCount, setQuantumParameterCount] = useState(40);
  const [signalType, setSignalType] = useState<"image" | "signal">("image");
  const metrics = calculateCompressionMetrics(quantumParameterCount, signalType);

  return (
    <LabShell
      title="quINR Compression Rate Explorer"
      summary="Compare classical INR and quINR compression ratios, PSNR, and residual behavior under different quantum parameter budgets."
      controls={
        <div className="simulation-control-grid">
          <label>
            Quantum parameter count: {quantumParameterCount}
            <input max={100} min={8} onChange={(event) => setQuantumParameterCount(Number(event.target.value))} type="range" value={quantumParameterCount} />
          </label>
          <label>
            Signal type
            <select onChange={(event) => setSignalType(event.target.value as "image" | "signal")} value={signalType}>
              <option value="image">Image</option>
              <option value="signal">Signal</option>
            </select>
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Compression ratio under the classical INR baseline." label="Classical ratio" value={`${metrics.classicalRatio}:1`} />
            <MetricTile detail="Compression ratio under the quINR variant." label="quINR ratio" value={`${metrics.quantumRatio}:1`} />
            <MetricTile detail="Peak signal-to-noise ratio under the quINR variant." label="quINR PSNR" value={`${metrics.quantumPsnr} dB`} />
          </div>
          <p className="simulation-status-copy">{metrics.residualFocus}</p>
        </div>
      }
    />
  );
}

function QgshapLab() {
  const [nodeCount, setNodeCount] = useState(8);
  const [sampleBudget, setSampleBudget] = useState(1024);
  const metrics = calculateQgshapMetrics(nodeCount, sampleBudget);

  return (
    <LabShell
      title="QGSHAP Explainability Accelerator"
      summary="Hold explanation quality constant and compare the sample complexity of classical SHAP versus a Grover-style amplitude-amplified path."
      controls={
        <div className="simulation-control-grid">
          <label>
            Graph nodes: {nodeCount}
            <input max={12} min={4} onChange={(event) => setNodeCount(Number(event.target.value))} type="range" value={nodeCount} />
          </label>
          <label>
            Sample budget: {sampleBudget}
            <input max={4096} min={64} onChange={(event) => setSampleBudget(Number(event.target.value))} step={64} type="range" value={sampleBudget} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Exact SHAP subset evaluation cost." label="Classical exact" value={metrics.exactCost.toLocaleString()} />
            <MetricTile detail="Monte Carlo sampled SHAP workload." label="Classical sampled" value={metrics.sampledCost.toLocaleString()} />
            <MetricTile detail="Amplitude-amplified sample requirement." label="QGSHAP" value={metrics.quantumCost.toLocaleString()} />
          </div>
          <p className="simulation-status-copy">
            Relative speedup against sampled SHAP: about {metrics.speedupVsSampled}x at the current sample budget.
          </p>
        </div>
      }
    />
  );
}

function SolverRaceLab() {
  const [problemSize, setProblemSize] = useState(48);
  const results = calculateSolverRace(problemSize);

  return (
    <LabShell
      title="Quantum vs. Classical Solver Race"
      summary="Watch runtime, objective gap, and rough hardware cost shift as the optimization problem grows."
      controls={
        <div className="simulation-control-grid">
          <label>
            Problem size: {problemSize}
            <input max={120} min={12} onChange={(event) => setProblemSize(Number(event.target.value))} type="range" value={problemSize} />
          </label>
        </div>
      }
      outputs={
        <div className="simulation-detail-list">
          {results.map((result) => (
            <div className="simulation-detail-item" key={result.name}>
              <strong>{result.name}</strong>
              <div className="simulation-progress">
                <span style={{ width: `${result.progressPercent}%` }} />
              </div>
              <p>
                Runtime {result.runtimeMs} ms, objective gap {result.objectiveGap}%, estimated cost ${result.costUsd}
              </p>
            </div>
          ))}
        </div>
      }
    />
  );
}

function PqcMigrationLab() {
  const [actions, setActions] = useState<Record<string, string>>(() =>
    Object.fromEntries(PQC_SERVICES.map((service) => [service.id, "Hold"])),
  );
  const result = evaluatePqcPlan(actions);

  return (
    <LabShell
      title="Post-Quantum Cryptography Migration Simulator"
      summary="Separate true public-key migration urgency from symmetric-key hygiene so the learner does not absorb the wrong cryptographic lesson."
      controls={
        <div className="simulation-detail-list">
          {PQC_SERVICES.map((service) => (
            <div className="simulation-detail-item" key={service.id}>
              <strong>
                {service.name} ({service.crypto})
              </strong>
              <select
                onChange={(event) =>
                  setActions((current) => ({
                    ...current,
                    [service.id]: event.target.value,
                  }))
                }
                value={actions[service.id]}
              >
                <option value="Hold">Hold</option>
                <option value="Upgrade to AES-256">Upgrade to AES-256</option>
                <option value="Migrate to ML-KEM">Migrate to ML-KEM</option>
                <option value="Migrate to ML-DSA">Migrate to ML-DSA</option>
                <option value="Migrate to SLH-DSA">Migrate to SLH-DSA</option>
              </select>
              <p>{service.rationale}</p>
            </div>
          ))}
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Services assigned the correct migration path." label="Correct plans" value={`${result.correctCount} / ${PQC_SERVICES.length}`} />
            <MetricTile detail="Vulnerable public-key or signature services still untreated." label="Critical remaining" value={String(result.criticalRemaining)} />
            <MetricTile detail="Threat rises when vulnerable public-key systems remain." label="Threat meter" value={`${result.threatPercent}%`} />
          </div>
          <p className="simulation-status-copy">
            AES-256 should remain in place. AES-128 upgrades to AES-256 as hygiene. The true PQC migration work targets RSA, ECC, and signature systems.
          </p>
        </div>
      }
    />
  );
}

function VerticalMapperLab() {
  const [verticalFilter, setVerticalFilter] = useState("All");
  const [maturityFilter, setMaturityFilter] = useState("All");
  const filtered = VERTICAL_CONNECTIONS.filter(
    (item) =>
      (verticalFilter === "All" || item.vertical === verticalFilter) &&
      (maturityFilter === "All" || item.maturity === maturityFilter),
  );
  const [selectedId, setSelectedId] = useState(filtered[0]?.id ?? VERTICAL_CONNECTIONS[0].id);
  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0] ?? null;

  return (
    <LabShell
      title="Industry Vertical Mapper"
      summary="Filter industry/application/horizon connections and open the source-grounded rationale behind each one."
      controls={
        <div className="simulation-control-grid">
          <label>
            Vertical
            <select onChange={(event) => setVerticalFilter(event.target.value)} value={verticalFilter}>
              <option value="All">All</option>
              {[...new Set(VERTICAL_CONNECTIONS.map((item) => item.vertical))].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Maturity
            <select onChange={(event) => setMaturityFilter(event.target.value)} value={maturityFilter}>
              <option value="All">All</option>
              {[...new Set(VERTICAL_CONNECTIONS.map((item) => item.maturity))].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <div className="simulation-choice-row">
            {filtered.map((item) => (
              <button
                className={`secondary-button ${selectedId === item.id ? "is-selected" : ""}`}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                type="button"
              >
                {item.vertical}
              </button>
            ))}
          </div>
        </div>
      }
      outputs={
        <div className="stack">
          {selected ? (
            <>
              <div className="simulation-metric-grid">
                <MetricTile detail="Application class currently highlighted." label="Application" value={selected.application} />
                <MetricTile detail="Commercial readiness level." label="Maturity" value={selected.maturity} />
                <MetricTile detail="Expected time horizon." label="Horizon" value={selected.horizon} />
              </div>
              <p className="simulation-status-copy">{selected.passage}</p>
            </>
          ) : (
            <p className="simulation-warning">
              No industry connections match the current filter combination. Relax one filter to restore the cross-vertical map.
            </p>
          )}
        </div>
      }
    />
  );
}

function ThermodynamicLab() {
  const [classicalAllocation, setClassicalAllocation] = useState(55);
  const [qpuShots, setQpuShots] = useState(180);
  const [memoryArchitecture, setMemoryArchitecture] = useState<MemoryArchitecture>("tiered");
  const metrics = calculateThermodynamicMetrics(classicalAllocation, qpuShots, memoryArchitecture);

  return (
    <LabShell
      title="Thermodynamic Cost Calculator"
      summary="Balance classical compute, QPU shots, and memory strategy while watching energy cost, memory burden, and solution quality move together."
      controls={
        <div className="simulation-control-grid">
          <label>
            Classical allocation: {classicalAllocation}
            <input max={100} min={10} onChange={(event) => setClassicalAllocation(Number(event.target.value))} type="range" value={classicalAllocation} />
          </label>
          <label>
            QPU shots: {qpuShots}
            <input max={400} min={20} onChange={(event) => setQpuShots(Number(event.target.value))} step={10} type="range" value={qpuShots} />
          </label>
          <label>
            Memory architecture
            <select onChange={(event) => setMemoryArchitecture(event.target.value as MemoryArchitecture)} value={memoryArchitecture}>
              <option value="standard">Standard</option>
              <option value="tiered">Tiered</option>
              <option value="cryogenic-aware">Cryogenic-aware</option>
            </select>
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Illustrative energy cost per task." label="Energy" value={`${metrics.energyJoules} J`} />
            <MetricTile detail="Modeled memory burden for the current architecture." label="Memory cost" value={`${metrics.memoryCost} units`} />
            <MetricTile detail="Current solution-quality estimate." label="Quality" value={`${metrics.quality}%`} />
          </div>
          <p className="simulation-status-copy">
            The current configuration sits about {metrics.landauerRatio.toExponential(2)}x above the Landauer limit reference line, which is why the limit is a baseline, not an engineering target.
          </p>
        </div>
      }
    />
  );
}

function RoadmapSorterLab() {
  const [placements, setPlacements] = useState<
    Record<string, { horizon: RoadmapHorizon; evidence: EvidenceStrength }>
  >(() =>
    Object.fromEntries(
      ROADMAP_CLAIMS.map((claim) => [
        claim.id,
        {
          horizon: "5 years" as RoadmapHorizon,
          evidence: "Moderate" as EvidenceStrength,
        },
      ]),
    ),
  );
  const result = evaluateRoadmapPlacements(placements);

  return (
    <LabShell
      title="Near-Term vs. Speculative Roadmap Sorter"
      summary="Place each claim by time horizon and evidence strength, then compare your judgment with the source-grounded rating."
      controls={
        <div className="simulation-detail-list">
          {ROADMAP_CLAIMS.map((claim) => (
            <div className="simulation-detail-item" key={claim.id}>
              <strong>{claim.claim}</strong>
              <div className="simulation-control-grid compact">
                <label>
                  Horizon
                  <select
                    onChange={(event) =>
                      setPlacements((current) => ({
                        ...current,
                        [claim.id]: {
                          ...current[claim.id],
                          horizon: event.target.value as RoadmapHorizon,
                        },
                      }))
                    }
                    value={placements[claim.id].horizon}
                  >
                    <option value="1 year">1 year</option>
                    <option value="5 years">5 years</option>
                    <option value="10 years">10 years</option>
                    <option value="Speculative">Speculative</option>
                  </select>
                </label>
                <label>
                  Evidence
                  <select
                    onChange={(event) =>
                      setPlacements((current) => ({
                        ...current,
                        [claim.id]: {
                          ...current[claim.id],
                          evidence: event.target.value as EvidenceStrength,
                        },
                      }))
                    }
                    value={placements[claim.id].evidence}
                  >
                    <option value="Strong">Strong</option>
                    <option value="Moderate">Moderate</option>
                    <option value="Weak">Weak</option>
                    <option value="None">None</option>
                  </select>
                </label>
              </div>
              <p className="muted">
                Source rating: {claim.correctHorizon}, {claim.correctEvidence}. {claim.rationale}
              </p>
            </div>
          ))}
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Claims placed in the same quadrant as the source synthesis." label="Correct placements" value={`${result.correct} / ${result.total}`} />
            <MetricTile detail="Roadmap literacy requires both timing and evidence judgment." label="Roadmap score" value={`${Math.round((result.correct / result.total) * 100)}%`} />
          </div>
          <p className="simulation-status-copy">
            Strong near-term claims usually concern routing, migration, and constrained workflow support; speculative claims usually leap beyond current hardware and validation.
          </p>
        </div>
      }
    />
  );
}

function renderLab(conceptId: string) {
  switch (conceptId) {
    case "SIM-01A":
      return <NISQFidelityLab />;
    case "SIM-01B":
      return <DecisionTreeLab />;
    case "SIM-01C":
      return <LaborSplitLab />;
    case "SIM-02A":
      return <RoutingSandboxLab />;
    case "SIM-02B":
      return <GraphShrinkingLab />;
    case "SIM-02C":
      return <ResidualLab />;
    case "SIM-03A":
      return <ArchitectureDissectorLab />;
    case "SIM-03B":
      return <KernelComparatorLab />;
    case "SIM-03C":
      return <FewShotLab />;
    case "SIM-04A":
      return <CompressionLab />;
    case "SIM-04B":
      return <QgshapLab />;
    case "SIM-05A":
      return <SolverRaceLab />;
    case "SIM-05B":
      return <PqcMigrationLab />;
    case "SIM-05C":
      return <VerticalMapperLab />;
    case "SIM-06A":
      return <ThermodynamicLab />;
    case "SIM-06B":
      return <RoadmapSorterLab />;
    default:
      return null;
  }
}

function SimulationConceptCard({
  concept,
  isOpen,
  onToggle,
}: {
  concept: SimulationConcept;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <article className="simulation-card">
      <div className="simulation-badge-row">
        <span className="simulation-chip">{concept.id}</span>
        <span className="simulation-chip tier">{concept.tier}</span>
        <span className="simulation-chip available">Live lab</span>
        {concept.correction ? <span className="simulation-chip corrected">Corrected</span> : null}
      </div>
      <h3>{concept.title}</h3>
      <p>{concept.summary}</p>
      <p className="muted">{concept.interaction}</p>
      {concept.formula ? <p className="simulation-formula">{concept.formula}</p> : null}
      {concept.correction ? <p className="simulation-callout">{concept.correction}</p> : null}
      {concept.emphasis ? <p className="simulation-emphasis">{concept.emphasis}</p> : null}
      <div className="button-row">
        <button className="primary-button" onClick={onToggle} type="button">
          {isOpen ? "Hide lab" : "Open lab"}
        </button>
      </div>
      {isOpen ? renderLab(concept.id) : null}
    </article>
  );
}

export function SimulationGallery({ modules }: { modules: SimulationModule[] }) {
  const [openConceptId, setOpenConceptId] = useState("SIM-01A");

  return (
    <div className="simulation-module-list">
      {modules.map((module) => (
        <article className="panel simulation-module-block" key={module.slug}>
          <div className="module-card-header">
            <div className="stack">
              <p className="eyebrow">Module {module.moduleNumber}</p>
              <h2>{module.title}</h2>
              <p>{module.summary}</p>
            </div>
          </div>

          <div className="simulation-card-grid">
            {module.concepts.map((concept) => (
              <SimulationConceptCard
                concept={concept}
                isOpen={openConceptId === concept.id}
                key={concept.id}
                onToggle={() => setOpenConceptId((current) => (current === concept.id ? "" : concept.id))}
              />
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}
