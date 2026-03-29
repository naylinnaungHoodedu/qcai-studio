import assert from "node:assert/strict";
import test from "node:test";

import {
  AI_ROUTING_SEQUENCE,
  INITIAL_ROUTING_MAPPING,
  PQC_SERVICES,
  applyRoutingSwap,
  calculateNisqSimulation,
  evaluateGraphShrinking,
  evaluatePqcPlan,
  evaluateRoutingMapping,
} from "../src/lib/simulation-models";
import { SIMULATION_STATUS_NOTE } from "../src/lib/simulations";

test("nisq simulation keeps the ideal backend above noisy hardware at the same controls", () => {
  const noisy = calculateNisqSimulation({
    depth: 40,
    gateErrorRatePct: 1,
    qubitCount: 20,
    backendId: "ibm-heron",
  });
  const ideal = calculateNisqSimulation({
    depth: 40,
    gateErrorRatePct: 1,
    qubitCount: 20,
    backendId: "simulated-ideal",
  });

  assert.ok(
    (ideal.points.at(-1)?.fidelity ?? 0) > (noisy.points.at(-1)?.fidelity ?? 0),
  );
});

test("ai routing sequence satisfies all required interactions with one swap path", () => {
  const finalMapping = AI_ROUTING_SEQUENCE.reduce(
    (current, swapId) => applyRoutingSwap(current, swapId),
    INITIAL_ROUTING_MAPPING,
  );
  const result = evaluateRoutingMapping(finalMapping, AI_ROUTING_SEQUENCE.length);

  assert.equal(result.satisfied, 3);
  assert.equal(result.unsatisfied, 0);
});

test("graph shrinking target can be met without dropping below ninety percent quality", () => {
  const result = evaluateGraphShrinking(["merge", "absorb", "factor"]);

  assert.equal(result.qubits, 8);
  assert.equal(result.quality, 94);
  assert.equal(result.targetMet, true);
});

test("pqc migration keeps aes-256 services on hold instead of forcing pqc migration", () => {
  const actions = Object.fromEntries(PQC_SERVICES.map((service) => [service.id, service.correctAction]));
  const aes256Services = PQC_SERVICES.filter((service) => service.crypto === "AES-256");

  for (const service of aes256Services) {
    assert.equal(actions[service.id], "Hold");
  }

  const result = evaluatePqcPlan(actions);
  assert.equal(result.criticalRemaining, 0);
  assert.equal(result.correctCount, PQC_SERVICES.length);
});

test("simulation status note now promises live browser labs instead of roadmap-only copy", () => {
  assert.match(SIMULATION_STATUS_NOTE, /run live in the browser today/i);
  assert.doesNotMatch(SIMULATION_STATUS_NOTE, /without claiming that all 16 simulations are already live/i);
});
