"use client";

import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";

import type { AcademySimulationRecord } from "@/lib/academy-simulations";

type Complex = {
  re: number;
  im: number;
};

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function toRadians(value: number) {
  return (value * Math.PI) / 180;
}

function complex(re: number, im = 0): Complex {
  return { re, im };
}

function complexAdd(a: Complex, b: Complex): Complex {
  return complex(a.re + b.re, a.im + b.im);
}

function complexMultiply(a: Complex, b: Complex): Complex {
  return complex(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
}

function complexScale(a: Complex, scale: number): Complex {
  return complex(a.re * scale, a.im * scale);
}

function complexMagnitudeSquared(value: Complex) {
  return value.re ** 2 + value.im ** 2;
}

function complexPhase(value: Complex) {
  return (Math.atan2(value.im, value.re) * 180) / Math.PI;
}

function formatComplex(value: Complex) {
  const re = value.re.toFixed(2);
  const im = Math.abs(value.im).toFixed(2);
  const sign = value.im >= 0 ? "+" : "-";
  return `${re} ${sign} ${im}i`;
}

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function normalizedWeights(values: number[]) {
  const positive = values.map((value) => Math.max(value, 0.05));
  const total = positive.reduce((sum, value) => sum + value, 0);
  return positive.map((value) => value / total);
}

function stateFromAngles(thetaDeg: number, phiDeg: number): [Complex, Complex] {
  const theta = toRadians(thetaDeg);
  const phi = toRadians(phiDeg);
  return [
    complex(Math.cos(theta / 2), 0),
    complex(Math.sin(theta / 2) * Math.cos(phi), Math.sin(theta / 2) * Math.sin(phi)),
  ];
}

function applySingleQubitGate(
  state: [Complex, Complex],
  gate: [[Complex, Complex], [Complex, Complex]],
): [Complex, Complex] {
  return [
    complexAdd(complexMultiply(gate[0][0], state[0]), complexMultiply(gate[0][1], state[1])),
    complexAdd(complexMultiply(gate[1][0], state[0]), complexMultiply(gate[1][1], state[1])),
  ];
}

const SINGLE_QUBIT_GATES: Record<
  string,
  [[Complex, Complex], [Complex, Complex]]
> = {
  H: [
    [complexScale(complex(1), 1 / Math.sqrt(2)), complexScale(complex(1), 1 / Math.sqrt(2))],
    [complexScale(complex(1), 1 / Math.sqrt(2)), complexScale(complex(-1), 1 / Math.sqrt(2))],
  ],
  X: [
    [complex(0), complex(1)],
    [complex(1), complex(0)],
  ],
  Y: [
    [complex(0), complex(0, -1)],
    [complex(0, 1), complex(0)],
  ],
  Z: [
    [complex(1), complex(0)],
    [complex(0), complex(-1)],
  ],
  S: [
    [complex(1), complex(0)],
    [complex(0), complex(0, 1)],
  ],
  T: [
    [complex(1), complex(0)],
    [complex(0), complex(Math.SQRT1_2, Math.SQRT1_2)],
  ],
};

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
            <strong>{formatter ? formatter(item.value) : item.value.toFixed(2)}</strong>
            <p>{item.label}</p>
          </div>
        );
      })}
    </div>
  );
}

function LabShell({
  accentColor,
  title,
  summary,
  controls,
  outputs,
}: {
  accentColor: string;
  title: string;
  summary: string;
  controls: ReactNode;
  outputs: ReactNode;
}) {
  return (
    <div
      className="simulation-lab academy-lab-shell"
      style={
        {
          ["--academy-accent" as string]: accentColor,
          ["--academy-accent-soft" as string]: `${accentColor}20`,
          ["--academy-accent-strong" as string]: `${accentColor}40`,
        } as CSSProperties
      }
    >
      <div className="simulation-lab-header">
        <div>
          <p className="eyebrow">Interactive academy lab</p>
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

function BlochSphereLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [prepareTheta, setPrepareTheta] = useState(60);
  const [preparePhi, setPreparePhi] = useState(25);
  const [state, setState] = useState<[Complex, Complex]>(() => stateFromAngles(60, 25));
  const p0 = complexMagnitudeSquared(state[0]) * 100;
  const p1 = complexMagnitudeSquared(state[1]) * 100;
  const x = 2 * (state[0].re * state[1].re + state[0].im * state[1].im);
  const y = 2 * (state[0].im * state[1].re - state[0].re * state[1].im);
  const z = complexMagnitudeSquared(state[0]) - complexMagnitudeSquared(state[1]);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Prepare a qubit from polar and azimuthal angles, then apply common single-qubit gates and watch its Bloch coordinates update."
      controls={
        <div className="stack">
          <div className="simulation-control-grid">
            <label>
              Theta: {prepareTheta} deg
              <input max={180} min={0} onChange={(event) => setPrepareTheta(Number(event.target.value))} type="range" value={prepareTheta} />
            </label>
            <label>
              Phi: {preparePhi} deg
              <input max={180} min={-180} onChange={(event) => setPreparePhi(Number(event.target.value))} type="range" value={preparePhi} />
            </label>
          </div>

          <div className="button-row">
            <button className="secondary-button" onClick={() => setState(stateFromAngles(prepareTheta, preparePhi))} type="button">
              Prepare state
            </button>
            {["X", "Y", "Z", "H", "S", "T"].map((gate) => (
              <button
                className="secondary-button"
                key={gate}
                onClick={() => setState((current) => applySingleQubitGate(current, SINGLE_QUBIT_GATES[gate]))}
                type="button"
              >
                {gate}
              </button>
            ))}
          </div>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Probability of measuring |0>." label="P(|0>)" value={formatPercent(p0)} />
            <MetricTile detail="Probability of measuring |1>." label="P(|1>)" value={formatPercent(p1)} />
            <MetricTile detail="Relative phase of the |1> amplitude." label="Phase" value={`${complexPhase(state[1]).toFixed(1)} deg`} />
          </div>
          <ChartBars
            formatter={(value) => value.toFixed(2)}
            maxValue={1}
            values={[
              { label: "x", value: Math.abs(x) },
              { label: "y", value: Math.abs(y) },
              { label: "z", value: Math.abs(z) },
            ]}
          />
          <p className="simulation-formula">
            |psi&gt; = ({formatComplex(state[0])})|0&gt; + ({formatComplex(state[1])})|1&gt;
          </p>
        </div>
      }
    />
  );
}

function SuperpositionLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [alphaMagnitude, setAlphaMagnitude] = useState(0.74);
  const [phaseDeg, setPhaseDeg] = useState(45);
  const [basis, setBasis] = useState<"Z" | "X" | "Custom">("Z");
  const [customAngle, setCustomAngle] = useState(35);
  const betaMagnitude = Math.sqrt(Math.max(1 - alphaMagnitude ** 2, 0));
  const state: [Complex, Complex] = [
    complex(alphaMagnitude, 0),
    complex(betaMagnitude * Math.cos(toRadians(phaseDeg)), betaMagnitude * Math.sin(toRadians(phaseDeg))),
  ];
  const basisAngle = basis === "Z" ? 0 : basis === "X" ? 90 : customAngle;
  const basisVector = [complex(Math.cos(toRadians(basisAngle / 2))), complex(Math.sin(toRadians(basisAngle / 2)))];
  const overlap = complexAdd(
    complexMultiply(basisVector[0], state[0]),
    complexMultiply(basisVector[1], state[1]),
  );
  const basisZeroProbability = clamp(complexMagnitudeSquared(overlap) * 100, 0, 100);
  const basisOneProbability = 100 - basisZeroProbability;
  const coherence = alphaMagnitude * betaMagnitude * Math.cos(toRadians(phaseDeg));

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Move the amplitudes and phase directly, then compare how the same qubit looks under different measurement bases."
      controls={
        <div className="simulation-control-grid">
          <label>
            |alpha|: {alphaMagnitude.toFixed(2)}
            <input max={1} min={0} onChange={(event) => setAlphaMagnitude(Number(event.target.value))} step={0.01} type="range" value={alphaMagnitude} />
          </label>
          <label>
            Relative phase: {phaseDeg} deg
            <input max={180} min={-180} onChange={(event) => setPhaseDeg(Number(event.target.value))} type="range" value={phaseDeg} />
          </label>
          <label>
            Basis
            <select onChange={(event) => setBasis(event.target.value as "Z" | "X" | "Custom")} value={basis}>
              <option value="Z">Computational Z</option>
              <option value="X">Hadamard X</option>
              <option value="Custom">Custom</option>
            </select>
          </label>
          <label>
            Custom basis angle: {customAngle} deg
            <input disabled={basis !== "Custom"} max={180} min={0} onChange={(event) => setCustomAngle(Number(event.target.value))} type="range" value={customAngle} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Measurement probability in the selected basis." label="Basis |0>" value={formatPercent(basisZeroProbability)} />
            <MetricTile detail="Complementary basis-state probability." label="Basis |1>" value={formatPercent(basisOneProbability)} />
            <MetricTile detail="Positive means constructive support in the chosen phase relation." label="Coherence" value={coherence.toFixed(2)} />
          </div>
          <ChartBars
            formatter={(value) => formatPercent(value * 100)}
            maxValue={1}
            values={[
              { label: "|alpha|^2", value: alphaMagnitude ** 2 },
              { label: "|beta|^2", value: betaMagnitude ** 2 },
              { label: "basis |0>", value: basisZeroProbability / 100 },
              { label: "basis |1>", value: basisOneProbability / 100 },
            ]}
          />
          <p className="simulation-formula">
            |psi&gt; = ({formatComplex(state[0])})|0&gt; + ({formatComplex(state[1])})|1&gt;
          </p>
        </div>
      }
    />
  );
}

function InterferenceLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [wavelength, setWavelength] = useState(0.5);
  const [pathDifference, setPathDifference] = useState(2);
  const [amplitude, setAmplitude] = useState(0.4);
  const [screenDistance, setScreenDistance] = useState(35);
  const phaseDifference = ((2 * Math.PI * pathDifference) / wavelength) % (2 * Math.PI);
  const intensity = 4 * amplitude ** 2 * Math.cos(phaseDifference / 2) ** 2;
  const fringeSpacing = (wavelength * screenDistance) / Math.max(pathDifference, 0.2);
  const detectorProfile = Array.from({ length: 7 }, (_, index) => {
    const x = index - 3;
    const envelope = Math.exp(-(x ** 2) / 9);
    const value = amplitude ** 2 * (1 + Math.cos(phaseDifference + x * 0.8)) * envelope;
    return { label: `D${index + 1}`, value: Math.max(value, 0.02) };
  });

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Treat interference as controllable phase accumulation: path length and wavelength decide whether the detector sees reinforcement or cancellation."
      controls={
        <div className="simulation-control-grid">
          <label>
            Wavelength lambda: {wavelength.toFixed(2)}
            <input max={1.2} min={0.2} onChange={(event) => setWavelength(Number(event.target.value))} step={0.05} type="range" value={wavelength} />
          </label>
          <label>
            Path difference d: {pathDifference.toFixed(2)}
            <input max={4} min={0.2} onChange={(event) => setPathDifference(Number(event.target.value))} step={0.05} type="range" value={pathDifference} />
          </label>
          <label>
            Amplitude a: {amplitude.toFixed(2)}
            <input max={1} min={0.1} onChange={(event) => setAmplitude(Number(event.target.value))} step={0.01} type="range" value={amplitude} />
          </label>
          <label>
            Detector distance L: {screenDistance}
            <input max={60} min={10} onChange={(event) => setScreenDistance(Number(event.target.value))} type="range" value={screenDistance} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Phase gap between the two paths." label="Delta phi" value={`${((phaseDifference * 180) / Math.PI).toFixed(1)} deg`} />
            <MetricTile detail="Relative detector intensity at the center." label="Center intensity" value={intensity.toFixed(2)} />
            <MetricTile detail="Approximate spacing between bright fringes." label="Fringe spacing" value={fringeSpacing.toFixed(2)} />
          </div>
          <ChartBars formatter={(value) => value.toFixed(2)} maxValue={1.6} values={detectorProfile} />
          <p className="simulation-status-copy">
            The detector brightens when phase difference approaches 0 deg or 360 deg, and dims when the
            paths drift toward a 180 deg mismatch.
          </p>
        </div>
      }
    />
  );
}

function TunnelingLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [barrierWidth, setBarrierWidth] = useState(0.9);
  const [barrierHeight, setBarrierHeight] = useState(3);
  const [packetEnergy, setPacketEnergy] = useState(1.1);
  const transmission =
    packetEnergy >= barrierHeight
      ? clamp(68 + (packetEnergy - barrierHeight) * 18 - barrierWidth * 6, 8, 98)
      : clamp(Math.exp(-2.2 * barrierWidth * Math.sqrt(barrierHeight - packetEnergy + 0.05)) * 100, 0.4, 92);
  const reflection = 100 - transmission;
  const decayLength =
    packetEnergy >= barrierHeight ? "oscillatory" : `${(1 / Math.sqrt(barrierHeight - packetEnergy + 0.1)).toFixed(2)} units`;
  const barrierProfile = [
    { label: "incident", value: 1 },
    { label: "inside barrier", value: Math.max(transmission / 100, 0.04) },
    { label: "transmitted", value: transmission / 100 },
  ];

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Model the barrier as a tunable gatekeeper: as width or height rises, classical intuition says stop, but the quantum tail can still leak through."
      controls={
        <div className="simulation-control-grid">
          <label>
            Barrier width: {barrierWidth.toFixed(2)}
            <input max={2} min={0.2} onChange={(event) => setBarrierWidth(Number(event.target.value))} step={0.05} type="range" value={barrierWidth} />
          </label>
          <label>
            Barrier height: {barrierHeight.toFixed(2)}
            <input max={5} min={0.5} onChange={(event) => setBarrierHeight(Number(event.target.value))} step={0.05} type="range" value={barrierHeight} />
          </label>
          <label>
            Packet energy: {packetEnergy.toFixed(2)}
            <input max={5} min={0.2} onChange={(event) => setPacketEnergy(Number(event.target.value))} step={0.05} type="range" value={packetEnergy} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Probability the packet crosses the barrier." label="Transmission" value={formatPercent(transmission)} />
            <MetricTile detail="Probability reflected back toward the source." label="Reflection" value={formatPercent(reflection)} />
            <MetricTile detail="Qualitative penetration depth inside the barrier." label="Decay length" value={decayLength} />
          </div>
          <ChartBars formatter={(value) => value.toFixed(2)} maxValue={1} values={barrierProfile} />
          <p className="simulation-status-copy">
            Even below the barrier, non-zero transmission survives because the wavefunction decays
            continuously rather than stopping at a hard classical wall.
          </p>
        </div>
      }
    />
  );
}

function EntanglementLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [bellState, setBellState] = useState<"Phi+" | "Phi-" | "Psi+" | "Psi-">("Phi+");
  const [aliceAngle, setAliceAngle] = useState(0);
  const [bobAngle, setBobAngle] = useState(45);
  const phaseShift = bellState === "Phi+" ? 0 : bellState === "Phi-" ? 180 : bellState === "Psi+" ? 90 : -90;
  const correlation = Math.cos(toRadians(aliceAngle - bobAngle + phaseShift));
  const sameOutcome = clamp(((1 + correlation) / 2) * 100, 0, 100);
  const differentOutcome = 100 - sameOutcome;
  const chsh = Math.abs(
    correlation -
      Math.cos(toRadians(aliceAngle - (bobAngle + 45) + phaseShift)) +
      Math.cos(toRadians((aliceAngle + 45) - bobAngle + phaseShift)) +
      Math.cos(toRadians((aliceAngle + 45) - (bobAngle + 45) + phaseShift)),
  );

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Entanglement becomes visible as a joint measurement pattern: changing Alice and Bob's settings reveals how the pair behaves as one correlated system."
      controls={
        <div className="simulation-control-grid">
          <label>
            Bell state
            <select onChange={(event) => setBellState(event.target.value as "Phi+" | "Phi-" | "Psi+" | "Psi-")} value={bellState}>
              <option value="Phi+">Phi+</option>
              <option value="Phi-">Phi-</option>
              <option value="Psi+">Psi+</option>
              <option value="Psi-">Psi-</option>
            </select>
          </label>
          <label>
            Alice angle: {aliceAngle} deg
            <input max={180} min={0} onChange={(event) => setAliceAngle(Number(event.target.value))} type="range" value={aliceAngle} />
          </label>
          <label>
            Bob angle: {bobAngle} deg
            <input max={180} min={0} onChange={(event) => setBobAngle(Number(event.target.value))} type="range" value={bobAngle} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Expectation value for the current measurement pair." label="Correlation E" value={correlation.toFixed(2)} />
            <MetricTile detail="Chance of matching Alice and Bob outcomes." label="Same outcome" value={formatPercent(sameOutcome)} />
            <MetricTile detail="Illustrative CHSH-like score with nearby settings." label="S score" value={chsh.toFixed(2)} />
          </div>
          <ChartBars
            formatter={(value) => formatPercent(value * 100)}
            maxValue={1}
            values={[
              { label: "same", value: sameOutcome / 100 },
              { label: "different", value: differentOutcome / 100 },
              { label: "|E|", value: Math.abs(correlation) },
            ]}
          />
          <p className="simulation-status-copy">
            The important lesson is relational: local states alone do not explain the pair. The
            structure is visible in the joint statistics.
          </p>
        </div>
      }
    />
  );
}

function MeasurementCollapseLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [stateAngle, setStateAngle] = useState(45);
  const [basis, setBasis] = useState<"Z" | "X">("Z");
  const [shots, setShots] = useState(40);
  const [counts, setCounts] = useState<{ zero: number; one: number }>({ zero: 0, one: 0 });
  const basisAngle = basis === "Z" ? 0 : 90;
  const zeroProbability = ((1 + Math.cos(toRadians(stateAngle - basisAngle))) / 2) * 100;

  function runExperiment() {
    let zero = 0;
    for (let index = 0; index < shots; index += 1) {
      if (Math.random() * 100 < zeroProbability) {
        zero += 1;
      }
    }
    setCounts({ zero, one: shots - zero });
  }

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Repeated measurement turns a probability distribution into concrete counts; the more shots you take, the closer the histogram leans toward the Born-rule expectation."
      controls={
        <div className="stack">
          <div className="simulation-control-grid">
            <label>
              State angle: {stateAngle} deg
              <input max={180} min={0} onChange={(event) => setStateAngle(Number(event.target.value))} type="range" value={stateAngle} />
            </label>
            <label>
              Basis
              <select onChange={(event) => setBasis(event.target.value as "Z" | "X")} value={basis}>
                <option value="Z">Computational Z</option>
                <option value="X">Hadamard X</option>
              </select>
            </label>
            <label>
              Shots: {shots}
              <input max={200} min={10} onChange={(event) => setShots(Number(event.target.value))} step={10} type="range" value={shots} />
            </label>
          </div>
          <div className="button-row">
            <button className="primary-button" onClick={runExperiment} type="button">
              Run shots
            </button>
          </div>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Expected probability before sampling." label="Expected p(0)" value={formatPercent(zeroProbability)} />
            <MetricTile detail="Observed count of |0> outcomes." label="Observed 0" value={String(counts.zero)} />
            <MetricTile detail="Observed count of |1> outcomes." label="Observed 1" value={String(counts.one)} />
          </div>
          <ChartBars formatter={(value) => String(Math.round(value))} maxValue={Math.max(shots, 1)} values={[{ label: "0", value: counts.zero }, { label: "1", value: counts.one }]} />
          <p className="simulation-status-copy">
            Before measurement the state carries amplitudes. After measurement you only keep sampled
            outcomes, so repetition is what reveals the original distribution.
          </p>
        </div>
      }
    />
  );
}

function TeleportationLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [theta, setTheta] = useState(45);
  const [phi, setPhi] = useState(45);
  const [step, setStep] = useState(1);
  const bitOne = theta > 90 ? 1 : 0;
  const bitTwo = phi >= 0 ? 0 : 1;
  const correction = `${bitOne ? "X " : ""}${bitTwo ? "Z" : ""}`.trim() || "Identity";
  const fidelity = clamp(step * 24 + 3, 0, 99);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Teleportation is a protocol, not a magic jump: a Bell measurement plus two classical bits determine which correction Bob must apply."
      controls={
        <div className="simulation-control-grid">
          <label>
            Message theta: {theta} deg
            <input max={180} min={0} onChange={(event) => setTheta(Number(event.target.value))} type="range" value={theta} />
          </label>
          <label>
            Message phi: {phi} deg
            <input max={180} min={-180} onChange={(event) => setPhi(Number(event.target.value))} type="range" value={phi} />
          </label>
          <label>
            Protocol step: {step}
            <input max={4} min={1} onChange={(event) => setStep(Number(event.target.value))} type="range" value={step} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="First classical bit from the Bell measurement." label="Bit 1" value={String(bitOne)} />
            <MetricTile detail="Second classical bit from the Bell measurement." label="Bit 2" value={String(bitTwo)} />
            <MetricTile detail="Correction Bob applies to recover the message." label="Correction" value={correction} />
          </div>
          <ChartBars
            formatter={(value) => formatPercent(value * 100)}
            maxValue={1}
            values={[
              { label: "prepared", value: 1 },
              { label: "shared pair", value: step >= 2 ? 1 : 0.3 },
              { label: "corrected", value: fidelity / 100 },
            ]}
          />
          <p className="simulation-status-copy">
            The message never travels as an independent particle. What moves forward are two classical
            bits and a correction rule anchored to a pre-shared entangled pair.
          </p>
        </div>
      }
    />
  );
}

function DeutschJozsaLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [oracleFamily, setOracleFamily] = useState<"Balanced" | "Constant">("Balanced");
  const [inputBits, setInputBits] = useState(3);
  const [speed, setSpeed] = useState(1.5);
  const classicalQueries = 2 ** (inputBits - 1) + 1;
  const quantumQueries = 1;
  const signature =
    oracleFamily === "Constant" ? "000" : inputBits === 2 ? "10" : inputBits === 3 ? "101" : "1011";

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Deutsch-Jozsa works by engineering interference so one quantum query separates constant from balanced oracle families."
      controls={
        <div className="simulation-control-grid">
          <label>
            Oracle family
            <select onChange={(event) => setOracleFamily(event.target.value as "Balanced" | "Constant")} value={oracleFamily}>
              <option value="Balanced">Balanced</option>
              <option value="Constant">Constant</option>
            </select>
          </label>
          <label>
            Input bits: {inputBits}
            <input max={4} min={2} onChange={(event) => setInputBits(Number(event.target.value))} type="range" value={inputBits} />
          </label>
          <label>
            Playback speed: {speed.toFixed(1)}x
            <input max={3} min={0.5} onChange={(event) => setSpeed(Number(event.target.value))} step={0.1} type="range" value={speed} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Quantum oracle calls stay fixed." label="Quantum queries" value={String(quantumQueries)} />
            <MetricTile detail="Classical worst-case queries for certainty." label="Classical queries" value={String(classicalQueries)} />
            <MetricTile detail="Idealized final-register signature." label="Output" value={signature} />
          </div>
          <p className="simulation-status-copy">
            Constant oracles return the all-zero signature after the final Hadamards. Balanced oracles
            leave a non-zero pattern because the amplitudes cancel differently.
          </p>
        </div>
      }
    />
  );
}

function QftLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [qubits, setQubits] = useState(3);
  const [period, setPeriod] = useState(4);
  const [shift, setShift] = useState(1);
  const stateCount = 2 ** qubits;
  const safePeriod = Math.max(period, 1);
  const peaks = Array.from({ length: stateCount }, (_, index) => {
    const distance = Math.min(
      ...Array.from({ length: safePeriod }, (_, multiple) =>
        Math.abs(index - multiple * (stateCount / safePeriod) - shift),
      ),
    );
    const value = Math.exp(-(distance ** 2) / 1.8);
    return { label: `|${index}>`, value };
  });
  const strongestPeak = peaks.reduce((best, item) => (item.value > best.value ? item : best), peaks[0]);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="The QFT turns periodic structure into concentrated frequency peaks, making hidden regularity visible before the classical post-processing begins."
      controls={
        <div className="simulation-control-grid">
          <label>
            Qubits: {qubits}
            <input max={4} min={2} onChange={(event) => setQubits(Number(event.target.value))} type="range" value={qubits} />
          </label>
          <label>
            Period: {period}
            <input max={8} min={2} onChange={(event) => setPeriod(Number(event.target.value))} type="range" value={period} />
          </label>
          <label>
            Phase shift: {shift}
            <input max={4} min={0} onChange={(event) => setShift(Number(event.target.value))} type="range" value={shift} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Hilbert-space size in the chosen register." label="Basis states" value={String(stateCount)} />
            <MetricTile detail="Most intense spectral bin after the QFT." label="Strongest peak" value={strongestPeak.label} />
            <MetricTile detail="Spacing implied by the chosen periodicity." label="Peak interval" value={(stateCount / safePeriod).toFixed(2)} />
          </div>
          <ChartBars formatter={(value) => value.toFixed(2)} maxValue={1} values={peaks} />
          <p className="simulation-status-copy">
            The transform does not solve factoring by itself; it exposes periodic structure in a basis
            where classical post-processing can exploit it.
          </p>
        </div>
      }
    />
  );
}

function greatestCommonDivisor(a: number, b: number): number {
  let x = a;
  let y = b;
  while (y !== 0) {
    const next = x % y;
    x = y;
    y = next;
  }
  return Math.abs(x);
}

function modularPower(base: number, exponent: number, modulus: number) {
  let result = 1;
  for (let step = 0; step < exponent; step += 1) {
    result = (result * base) % modulus;
  }
  return result;
}

function findOrder(base: number, modulus: number) {
  for (let r = 1; r <= modulus; r += 1) {
    if (modularPower(base, r, modulus) === 1) {
      return r;
    }
  }
  return null;
}

function ShorLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [composite, setComposite] = useState(15);
  const [base, setBase] = useState(2);
  const gcd = greatestCommonDivisor(base, composite);
  const order = gcd === 1 ? findOrder(base, composite) : null;
  const halfPower = order ? modularPower(base, order / 2, composite) : null;
  const factorA =
    order && order % 2 === 0 && halfPower !== null
      ? greatestCommonDivisor(halfPower - 1, composite)
      : 1;
  const factorB =
    order && order % 2 === 0 && halfPower !== null
      ? greatestCommonDivisor(halfPower + 1, composite)
      : 1;
  const success =
    gcd > 1 ||
    (factorA > 1 && factorA < composite) ||
    (factorB > 1 && factorB < composite);
  const factors = gcd > 1 ? [gcd, composite / gcd] : [factorA, factorB].filter((value) => value > 1 && value < composite);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Shor-style period finding lives inside a wider factorization workflow: period discovery matters because classical number theory can turn an even order into real factors."
      controls={
        <div className="simulation-control-grid">
          <label>
            Composite N
            <select onChange={(event) => setComposite(Number(event.target.value))} value={composite}>
              {[15, 21, 33, 35].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Base a
            <select onChange={(event) => setBase(Number(event.target.value))} value={base}>
              {[2, 4, 5, 8, 11].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Immediate classical shortcut if gcd(a, N) > 1." label="gcd(a, N)" value={String(gcd)} />
            <MetricTile detail="Smallest r such that a^r mod N = 1." label="Order r" value={order ? String(order) : "not found"} />
            <MetricTile detail="Whether the current selection produces non-trivial factors." label="Status" value={success ? "Factorable" : "Retry"} />
          </div>
          <p className="simulation-status-copy">
            {success
              ? `Recovered non-trivial factors: ${factors.join(" x ")}.`
              : "This choice does not yield a clean even period with useful post-processing. Change the base and try again."}
          </p>
        </div>
      }
    />
  );
}

function GroverLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [databaseSize, setDatabaseSize] = useState(16);
  const [targetIndex, setTargetIndex] = useState(3);
  const [iterations, setIterations] = useState(2);
  const theta = Math.asin(1 / Math.sqrt(databaseSize));
  const targetProbability = Math.sin((2 * iterations + 1) * theta) ** 2;
  const optimalIterations = Math.max(Math.floor((Math.PI / 4) * Math.sqrt(databaseSize)), 1);
  const overshoot = iterations > optimalIterations;

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Grover amplification rotates amplitude toward the marked state. The trick is not just that probability rises, but that too many iterations start to undo the gain."
      controls={
        <div className="simulation-control-grid">
          <label>
            Database size N: {databaseSize}
            <input max={64} min={4} onChange={(event) => setDatabaseSize(Number(event.target.value))} step={4} type="range" value={databaseSize} />
          </label>
          <label>
            Target index: {targetIndex}
            <input max={databaseSize - 1} min={0} onChange={(event) => setTargetIndex(Number(event.target.value))} type="range" value={clamp(targetIndex, 0, databaseSize - 1)} />
          </label>
          <label>
            Iterations: {iterations}
            <input max={10} min={0} onChange={(event) => setIterations(Number(event.target.value))} type="range" value={iterations} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Current target-state probability." label="Target probability" value={formatPercent(targetProbability * 100)} />
            <MetricTile detail="Rule-of-thumb iteration count for the current search size." label="Optimal k" value={String(optimalIterations)} />
            <MetricTile detail="Overshooting causes the amplitude rotation to swing past the target." label="Regime" value={overshoot ? "Overshoot" : "On approach"} />
          </div>
          <ChartBars
            formatter={(value) => formatPercent(value * 100)}
            maxValue={1}
            values={[
              { label: `target ${targetIndex}`, value: targetProbability },
              { label: "others", value: ((1 - targetProbability) / Math.max(databaseSize - 1, 1)) * 4 },
            ]}
          />
          <p className="simulation-status-copy">
            Grover is best understood as a rotation in a two-dimensional subspace. Probability rises,
            peaks, and then falls again if you keep iterating.
          </p>
        </div>
      }
    />
  );
}

function UnitaryLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [sequence, setSequence] = useState<string[]>(["H"]);
  const state = sequence.reduce<[Complex, Complex]>(
    (current, gate) => applySingleQubitGate(current, SINGLE_QUBIT_GATES[gate]),
    [complex(1), complex(0)],
  );
  const pZero = complexMagnitudeSquared(state[0]) * 100;
  const pOne = complexMagnitudeSquared(state[1]) * 100;

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Treat single-qubit programming as gate composition: each button appends a unitary and the state updates immediately."
      controls={
        <div className="stack">
          <div className="button-row">
            {["H", "X", "Y", "Z", "S", "T"].map((gate) => (
              <button
                className="secondary-button"
                key={gate}
                onClick={() => setSequence((current) => [...current.slice(-7), gate])}
                type="button"
              >
                {gate}
              </button>
            ))}
          </div>
          <div className="button-row">
            <button className="secondary-button" onClick={() => setSequence([])} type="button">
              Reset
            </button>
            <button className="secondary-button" onClick={() => setSequence(["H", "S", "T"])} type="button">
              Load phase demo
            </button>
          </div>
          <p className="simulation-formula">{sequence.length ? sequence.join(" -> ") : "Identity circuit"}</p>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Probability of measuring |0> after the sequence." label="P(|0>)" value={formatPercent(pZero)} />
            <MetricTile detail="Probability of measuring |1> after the sequence." label="P(|1>)" value={formatPercent(pOne)} />
            <MetricTile detail="Circuit length in gates." label="Depth" value={String(sequence.length)} />
          </div>
          <p className="simulation-formula">
            |psi_out&gt; = ({formatComplex(state[0])})|0&gt; + ({formatComplex(state[1])})|1&gt;
          </p>
          <p className="simulation-status-copy">
            Unitary programming is reversible and amplitude-preserving until you choose to measure.
          </p>
        </div>
      }
    />
  );
}

function QiskitLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [rows, setRows] = useState(3);
  const [columns, setColumns] = useState(5);
  const [selectedRow, setSelectedRow] = useState(0);
  const [selectedColumn, setSelectedColumn] = useState(0);
  const [selectedGate, setSelectedGate] = useState<"H" | "X" | "RZ" | "CX">("H");
  const [cells, setCells] = useState<string[][]>(() => Array.from({ length: 3 }, () => Array.from({ length: 5 }, () => "")));

  function resetGrid(nextRows = rows, nextColumns = columns) {
    setCells(Array.from({ length: nextRows }, () => Array.from({ length: nextColumns }, () => "")));
  }

  function placeGate() {
    setCells((current) =>
      current.map((row, rowIndex) =>
        row.map((cell, columnIndex) => {
          if (rowIndex === selectedRow && columnIndex === selectedColumn) {
            return selectedGate;
          }
          return cell;
        }),
      ),
    );
  }

  const qiskitLines = cells.flatMap((row, rowIndex) =>
    row.flatMap((cell, columnIndex) => {
      if (!cell) {
        return [];
      }
      if (cell === "CX") {
        return [`qc.cx(${rowIndex}, ${Math.min(rowIndex + 1, rows - 1)})  # col ${columnIndex + 1}`];
      }
      if (cell === "RZ") {
        return [`qc.rz(0.5, ${rowIndex})  # col ${columnIndex + 1}`];
      }
      return [`qc.${cell.toLowerCase()}(${rowIndex})  # col ${columnIndex + 1}`];
    }),
  );

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="This is a bridge from visual placement to code literacy: build a tiny circuit on a grid, then inspect the generated Qiskit-flavored sketch."
      controls={
        <div className="stack">
          <div className="simulation-control-grid">
            <label>
              Qubits
              <select
                onChange={(event) => {
                  const nextRows = Number(event.target.value);
                  setRows(nextRows);
                  if (selectedRow >= nextRows) {
                    setSelectedRow(nextRows - 1);
                  }
                  resetGrid(nextRows, columns);
                }}
                value={rows}
              >
                {[2, 3].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Columns
              <select
                onChange={(event) => {
                  const nextColumns = Number(event.target.value);
                  setColumns(nextColumns);
                  if (selectedColumn >= nextColumns) {
                    setSelectedColumn(nextColumns - 1);
                  }
                  resetGrid(rows, nextColumns);
                }}
                value={columns}
              >
                {[4, 5, 6].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Row
              <select onChange={(event) => setSelectedRow(Number(event.target.value))} value={selectedRow}>
                {Array.from({ length: rows }, (_, index) => (
                  <option key={index} value={index}>
                    q{index}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Column
              <select onChange={(event) => setSelectedColumn(Number(event.target.value))} value={selectedColumn}>
                {Array.from({ length: columns }, (_, index) => (
                  <option key={index} value={index}>
                    {index + 1}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Gate
              <select onChange={(event) => setSelectedGate(event.target.value as "H" | "X" | "RZ" | "CX")} value={selectedGate}>
                {["H", "X", "RZ", "CX"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="button-row">
            <button className="primary-button" onClick={placeGate} type="button">
              Place gate
            </button>
            <button className="secondary-button" onClick={() => resetGrid()} type="button">
              Reset circuit
            </button>
          </div>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-table">
            {cells.map((row, rowIndex) => (
              <div className="simulation-table-row" key={`row-${rowIndex}`}>
                <span>q{rowIndex}</span>
                <span>{row.map((cell) => cell || ".").join("  ")}</span>
              </div>
            ))}
          </div>
          <p className="simulation-formula">{qiskitLines.length ? qiskitLines.join("\n") : "qc = QuantumCircuit(...)"}</p>
          <p className="simulation-status-copy">
            Small circuits become less abstract when a visual layout and a code sketch stay in sync.
          </p>
        </div>
      }
    />
  );
}

function StatevectorLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [preset, setPreset] = useState<"Bell pair" | "Phase kickback" | "Amplitude bias">("Bell pair");
  const [step, setStep] = useState(2);
  const presets: Record<string, Array<{ label: string; value: number }>> = {
    "Bell pair":
      step === 1
        ? [
            { label: "|00>", value: 0.5 },
            { label: "|10>", value: 0.5 },
            { label: "|01>", value: 0 },
            { label: "|11>", value: 0 },
          ]
        : [
            { label: "|00>", value: 0.5 },
            { label: "|11>", value: 0.5 },
            { label: "|01>", value: 0 },
            { label: "|10>", value: 0 },
          ],
    "Phase kickback": [
      { label: "|00>", value: 0.25 },
      { label: "|01>", value: 0.25 },
      { label: "|10>", value: 0.25 },
      { label: "|11>", value: 0.25 },
    ],
    "Amplitude bias": [
      { label: "|00>", value: 0.6 },
      { label: "|01>", value: 0.2 },
      { label: "|10>", value: 0.15 },
      { label: "|11>", value: 0.05 },
    ],
  };
  const statevector = presets[preset];
  const dominant = statevector.reduce((best, item) => (item.value > best.value ? item : best), statevector[0]);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="For tiny circuits the statevector is a debugging object: amplitudes, phases, and dominant basis states become readable instead of hidden."
      controls={
        <div className="simulation-control-grid">
          <label>
            Preset
            <select onChange={(event) => setPreset(event.target.value as "Bell pair" | "Phase kickback" | "Amplitude bias")} value={preset}>
              <option value="Bell pair">Bell pair</option>
              <option value="Phase kickback">Phase kickback</option>
              <option value="Amplitude bias">Amplitude bias</option>
            </select>
          </label>
          <label>
            Circuit step: {step}
            <input max={2} min={1} onChange={(event) => setStep(Number(event.target.value))} type="range" value={step} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Largest basis-state probability." label="Dominant state" value={dominant.label} />
            <MetricTile detail="Dominant probability mass." label="Dominant weight" value={formatPercent(dominant.value * 100)} />
            <MetricTile detail="Educational register size." label="Register" value="2 qubits" />
          </div>
          <ChartBars formatter={(value) => formatPercent(value * 100)} maxValue={1} values={statevector} />
          <p className="simulation-status-copy">
            Statevectors are only tractable for small systems, which is exactly why they are such a
            good educational tool: every basis component remains inspectable.
          </p>
        </div>
      }
    />
  );
}

function ErrorCorrectionLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [code, setCode] = useState<"Bit flip" | "Phase flip" | "Steane-lite">("Bit flip");
  const [errorType, setErrorType] = useState<"X" | "Z" | "Y">("X");
  const [errorQubit, setErrorQubit] = useState(1);
  const syndrome =
    code === "Bit flip"
      ? errorType === "X"
        ? `${errorQubit === 1 ? "10" : errorQubit === 2 ? "11" : "01"}`
        : "00"
      : code === "Phase flip"
        ? errorType === "Z"
          ? `${errorQubit === 1 ? "10" : errorQubit === 2 ? "11" : "01"}`
          : "00"
        : errorType === "Y"
          ? "111"
          : errorType === "X"
            ? "101"
            : "011";
  const recommended =
    syndrome === "00"
      ? "No correction"
      : code === "Bit flip" && errorType !== "X"
        ? "Code mismatch"
        : code === "Phase flip" && errorType !== "Z"
          ? "Code mismatch"
          : `${errorType} on qubit ${errorQubit}`;
  const recoverable = recommended !== "Code mismatch";

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="The point of the code is not magic immunity. It is structured redundancy: stabilizers expose syndromes, and the decoder maps those syndromes to a correction action."
      controls={
        <div className="simulation-control-grid">
          <label>
            Code family
            <select onChange={(event) => setCode(event.target.value as "Bit flip" | "Phase flip" | "Steane-lite")} value={code}>
              <option value="Bit flip">3-qubit bit-flip</option>
              <option value="Phase flip">3-qubit phase-flip</option>
              <option value="Steane-lite">Steane-lite</option>
            </select>
          </label>
          <label>
            Error type
            <select onChange={(event) => setErrorType(event.target.value as "X" | "Z" | "Y")} value={errorType}>
              <option value="X">X</option>
              <option value="Z">Z</option>
              <option value="Y">Y</option>
            </select>
          </label>
          <label>
            Error qubit: {errorQubit}
            <input max={3} min={1} onChange={(event) => setErrorQubit(Number(event.target.value))} type="range" value={errorQubit} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Measured stabilizer syndrome for the selected fault." label="Syndrome" value={syndrome} />
            <MetricTile detail="Decoder recommendation from the chosen code." label="Decoder" value={recommended} />
            <MetricTile detail="Whether the selected code family can repair the fault." label="Recoverable" value={recoverable ? "Yes" : "No"} />
          </div>
          <p className="simulation-status-copy">
            Compact educational codes teach the core idea: a code has to match the dominant error
            model, or the syndrome no longer implies a useful correction.
          </p>
        </div>
      }
    />
  );
}

function HybridMlLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [ansatz, setAnsatz] = useState<"RY-RZ" | "Hardware-efficient">("RY-RZ");
  const [optimizer, setOptimizer] = useState<"Grad descent" | "Random search">("Grad descent");
  const [thetaOne, setThetaOne] = useState(-0.3);
  const [thetaTwo, setThetaTwo] = useState(-1.4);
  const [learningRate, setLearningRate] = useState(0.15);
  const ansatzBias = ansatz === "RY-RZ" ? 0.08 : 0.02;
  const optimizerBias = optimizer === "Grad descent" ? 0.06 : -0.01;
  const loss = clamp(
    0.35 +
      Math.abs(thetaOne) * 0.18 +
      Math.abs(thetaTwo) * 0.1 -
      learningRate * 0.4 -
      ansatzBias -
      optimizerBias,
    0.06,
    0.98,
  );
  const validation = clamp(1 - loss + 0.08, 0.12, 0.99);
  const landscapePoints = Array.from({ length: 6 }, (_, index) => ({
    label: `E${index + 1}`,
    value: clamp(loss + index * 0.02 - learningRate * 0.18, 0.03, 0.95),
  }));

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Treat the hybrid model as an optimization system: the quantum block is one component inside a trainable loop, not a stand-alone predictor."
      controls={
        <div className="simulation-control-grid">
          <label>
            Ansatz
            <select onChange={(event) => setAnsatz(event.target.value as "RY-RZ" | "Hardware-efficient")} value={ansatz}>
              <option value="RY-RZ">1-qubit: RY-RZ</option>
              <option value="Hardware-efficient">Hardware-efficient</option>
            </select>
          </label>
          <label>
            Optimizer
            <select onChange={(event) => setOptimizer(event.target.value as "Grad descent" | "Random search")} value={optimizer}>
              <option value="Grad descent">Grad descent</option>
              <option value="Random search">Random search</option>
            </select>
          </label>
          <label>
            Theta 1: {thetaOne.toFixed(2)}
            <input max={3} min={-3} onChange={(event) => setThetaOne(Number(event.target.value))} step={0.01} type="range" value={thetaOne} />
          </label>
          <label>
            Theta 2: {thetaTwo.toFixed(2)}
            <input max={3} min={-3} onChange={(event) => setThetaTwo(Number(event.target.value))} step={0.01} type="range" value={thetaTwo} />
          </label>
          <label>
            Learning rate: {learningRate.toFixed(2)}
            <input max={0.4} min={0.01} onChange={(event) => setLearningRate(Number(event.target.value))} step={0.01} type="range" value={learningRate} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Toy training loss for the current configuration." label="Loss" value={loss.toFixed(2)} />
            <MetricTile detail="Held-out score for the compact validation slice." label="Validation" value={validation.toFixed(2)} />
            <MetricTile detail="Toy gap between train and validation behavior." label="Generalization gap" value={(validation - (1 - loss)).toFixed(2)} />
          </div>
          <ChartBars formatter={(value) => value.toFixed(2)} maxValue={1} values={landscapePoints} />
          <p className="simulation-status-copy">
            The key lesson is not raw accuracy. It is how ansatz choice, optimizer behavior, and
            parameter sensitivity together shape the training surface.
          </p>
        </div>
      }
    />
  );
}

function QaoaPortfolioLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [style, setStyle] = useState<"Balanced" | "Growth" | "Defensive">("Balanced");
  const [riskAversion, setRiskAversion] = useState(0.35);
  const [gamma, setGamma] = useState(0.63);
  const [beta, setBeta] = useState(-1.26);
  const styleTilt =
    style === "Growth" ? [0.52, 0.33, 0.15] : style === "Defensive" ? [0.22, 0.28, 0.5] : [0.34, 0.33, 0.33];
  const weights = normalizedWeights([
    styleTilt[0] + gamma * 0.4,
    styleTilt[1] + Math.abs(beta) * 0.16,
    styleTilt[2] + riskAversion * 0.5,
  ]);
  const expectedReturn =
    7.2 + weights[0] * 5.1 + weights[1] * 3.4 + weights[2] * 2.1 - riskAversion * 1.8;
  const volatility =
    8.4 + weights[0] * 7.2 + weights[1] * 5.4 + weights[2] * 3.8 + riskAversion * 9.5;
  const score = expectedReturn - riskAversion * (volatility / 10);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="Read QAOA-inspired finance as a decision surface: the learner tunes risk, mixing, and optimizer behavior while the portfolio weights and score rebalance."
      controls={
        <div className="simulation-control-grid">
          <label>
            Portfolio style
            <select onChange={(event) => setStyle(event.target.value as "Balanced" | "Growth" | "Defensive")} value={style}>
              <option value="Balanced">Balanced (3 assets)</option>
              <option value="Growth">Growth</option>
              <option value="Defensive">Defensive</option>
            </select>
          </label>
          <label>
            Risk aversion lambda: {riskAversion.toFixed(2)}
            <input max={1} min={0.05} onChange={(event) => setRiskAversion(Number(event.target.value))} step={0.01} type="range" value={riskAversion} />
          </label>
          <label>
            Gamma: {gamma.toFixed(2)}
            <input max={1.5} min={0.1} onChange={(event) => setGamma(Number(event.target.value))} step={0.01} type="range" value={gamma} />
          </label>
          <label>
            Beta: {beta.toFixed(2)}
            <input max={1.5} min={-1.5} onChange={(event) => setBeta(Number(event.target.value))} step={0.01} type="range" value={beta} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Toy expected annual return for the current weights." label="Expected return" value={`${expectedReturn.toFixed(1)}%`} />
            <MetricTile detail="Toy annualized volatility proxy." label="Volatility" value={`${volatility.toFixed(1)}%`} />
            <MetricTile detail="Risk-adjusted objective used in the lab." label="Objective score" value={score.toFixed(2)} />
          </div>
          <ChartBars
            formatter={(value) => formatPercent(value * 100)}
            maxValue={1}
            values={[
              { label: "asset A", value: weights[0] },
              { label: "asset B", value: weights[1] },
              { label: "asset C", value: weights[2] },
            ]}
          />
          <p className="simulation-status-copy">
            This prototype keeps the finance tradeoff visible: a higher-return mix usually comes with
            higher volatility, and lambda determines how hard the optimizer resists that.
          </p>
        </div>
      }
    />
  );
}

function MonteCarloLab({ simulation }: { simulation: AcademySimulationRecord }) {
  const [optionType, setOptionType] = useState<"European Call" | "European Put">("European Call");
  const [spot, setSpot] = useState(100);
  const [strike, setStrike] = useState(100);
  const [volatility, setVolatility] = useState(0.3);
  const [rate, setRate] = useState(0.02);
  const intrinsic = optionType === "European Call" ? Math.max(spot - strike, 0) : Math.max(strike - spot, 0);
  const timeValue = Math.max(volatility * spot * 0.28, 0.1);
  const discount = Math.exp(-rate);
  const price = intrinsic * 0.42 + timeValue * discount;
  const classicalPaths = Math.round(12000 + volatility * 32000);
  const amplitudeEstimationPaths = Math.round(Math.sqrt(classicalPaths) * 46);
  const confidenceBand = price * (0.06 + volatility * 0.08);

  return (
    <LabShell
      accentColor={simulation.subjectAccentColor}
      title={simulation.title}
      summary="This lab ties pricing to cost models: the payoff definition stays classical, but amplitude-estimation intuition changes how sample complexity scales."
      controls={
        <div className="simulation-control-grid">
          <label>
            Option type
            <select onChange={(event) => setOptionType(event.target.value as "European Call" | "European Put")} value={optionType}>
              <option value="European Call">European Call</option>
              <option value="European Put">European Put</option>
            </select>
          </label>
          <label>
            Spot S0: {spot}
            <input max={180} min={60} onChange={(event) => setSpot(Number(event.target.value))} type="range" value={spot} />
          </label>
          <label>
            Strike K: {strike}
            <input max={180} min={60} onChange={(event) => setStrike(Number(event.target.value))} type="range" value={strike} />
          </label>
          <label>
            Volatility sigma: {volatility.toFixed(2)}
            <input max={0.8} min={0.05} onChange={(event) => setVolatility(Number(event.target.value))} step={0.01} type="range" value={volatility} />
          </label>
          <label>
            Rate r: {rate.toFixed(2)}
            <input max={0.1} min={0} onChange={(event) => setRate(Number(event.target.value))} step={0.005} type="range" value={rate} />
          </label>
        </div>
      }
      outputs={
        <div className="stack">
          <div className="simulation-metric-grid">
            <MetricTile detail="Toy discounted option estimate." label="Estimated price" value={`$${price.toFixed(2)}`} />
            <MetricTile detail="Classical Monte Carlo path count." label="Classical paths" value={classicalPaths.toLocaleString()} />
            <MetricTile detail="Amplitude-estimation-style sample complexity." label="Quantum paths" value={amplitudeEstimationPaths.toLocaleString()} />
          </div>
          <p className="simulation-status-copy">
            Confidence band: +/- ${confidenceBand.toFixed(2)}. The product story is not a new payoff
            function. It is the possibility of lower sample complexity for the same pricing task.
          </p>
        </div>
      }
    />
  );
}

export function AcademySimulationLabRenderer({
  simulation,
}: {
  simulation: AcademySimulationRecord;
}) {
  switch (simulation.id) {
    case "QMI-01":
      return <BlochSphereLab simulation={simulation} />;
    case "QMI-02":
      return <SuperpositionLab simulation={simulation} />;
    case "QMI-03":
      return <InterferenceLab simulation={simulation} />;
    case "QMI-04":
      return <TunnelingLab simulation={simulation} />;
    case "QMI-05":
      return <EntanglementLab simulation={simulation} />;
    case "QMI-06":
      return <MeasurementCollapseLab simulation={simulation} />;
    case "QAL-01":
      return <TeleportationLab simulation={simulation} />;
    case "QAL-02":
      return <DeutschJozsaLab simulation={simulation} />;
    case "QAL-03":
      return <QftLab simulation={simulation} />;
    case "QAL-04":
      return <ShorLab simulation={simulation} />;
    case "QAL-05":
      return <GroverLab simulation={simulation} />;
    case "QPR-01":
      return <UnitaryLab simulation={simulation} />;
    case "QPR-02":
      return <QiskitLab simulation={simulation} />;
    case "QPR-03":
      return <StatevectorLab simulation={simulation} />;
    case "AQS-01":
      return <ErrorCorrectionLab simulation={simulation} />;
    case "AQS-02":
      return <HybridMlLab simulation={simulation} />;
    case "QFO-01":
      return <QaoaPortfolioLab simulation={simulation} />;
    case "QFO-02":
      return <MonteCarloLab simulation={simulation} />;
    default:
      return null;
  }
}
