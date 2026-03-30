import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  BUILDER_SLOT_HEIGHT,
  BUILDER_SLOT_WIDTH,
  getBuilderCanvasLayout,
  placeBuilderNode,
  removeBuilderNode,
} from "../src/lib/builder";
import { BuilderSlot } from "../src/lib/types";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const BUILDER_COMPONENT_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/components/builder-studio.tsx"),
  "utf8",
);
const GLOBAL_CSS_SOURCE = readFileSync(
  resolve(TEST_DIR, "../src/app/globals.css"),
  "utf8",
);

const QC_AI_SLOTS: BuilderSlot[] = [
  {
    id: "slot-ingest",
    label: "Step 1",
    description: "Capture the raw problem state before any model compression.",
    x: 8,
    y: 30,
  },
  {
    id: "slot-bottleneck",
    label: "Step 2",
    description: "Reduce dimensionality before quantum execution.",
    x: 28,
    y: 18,
  },
  {
    id: "slot-quantum",
    label: "Step 3",
    description: "Execute the specialized quantum subroutine.",
    x: 50,
    y: 30,
  },
  {
    id: "slot-measurement",
    label: "Step 4",
    description: "Read out the quantum state into classical values.",
    x: 72,
    y: 18,
  },
  {
    id: "slot-postprocess",
    label: "Step 5",
    description: "Translate outputs into actions, explanations, or rankings.",
    x: 84,
    y: 44,
  },
];

test("builder canvas layout keeps the workbench slots inside the safe frame", () => {
  const layout = getBuilderCanvasLayout(QC_AI_SLOTS);
  const ingest = layout.positions["slot-ingest"];
  const postprocess = layout.positions["slot-postprocess"];
  const bottleneck = layout.positions["slot-bottleneck"];

  assert.ok(ingest.x >= BUILDER_SLOT_WIDTH / 2);
  assert.ok(postprocess.x <= layout.width - BUILDER_SLOT_WIDTH / 2);
  assert.ok(bottleneck.y >= BUILDER_SLOT_HEIGHT / 2);
  assert.ok(postprocess.y <= layout.height - BUILDER_SLOT_HEIGHT / 2);
  assert.ok(ingest.x < layout.positions["slot-quantum"].x);
  assert.ok(layout.positions["slot-quantum"].x < postprocess.x);
});

test("placing a concept removes duplicate usage and replaces the target slot", () => {
  const next = placeBuilderNode(
    {
      "slot-ingest": "data-ingest",
      "slot-bottleneck": "feature-bottleneck",
      "slot-quantum": "measurement",
    },
    "slot-bottleneck",
    "measurement",
  );

  assert.deepEqual(next, {
    "slot-ingest": "data-ingest",
    "slot-bottleneck": "measurement",
  });
});

test("removing a concept clears only the requested slot", () => {
  const next = removeBuilderNode(
    {
      "slot-ingest": "data-ingest",
      "slot-bottleneck": "feature-bottleneck",
    },
    "slot-bottleneck",
  );

  assert.deepEqual(next, {
    "slot-ingest": "data-ingest",
  });
});

test("builder layout renders the scenario ladder before the workbench", () => {
  assert.match(
    BUILDER_COMPONENT_SOURCE,
    /<div className="builder-stage-stack">[\s\S]*?<section className="panel builder-scenario-panel">[\s\S]*?<section className="panel builder-workbench">/,
  );
});

test("builder workbench keeps the drag-and-drop columns side by side on desktop", () => {
  assert.match(
    GLOBAL_CSS_SOURCE,
    /\.builder-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1\.45fr\)\s+minmax\(320px,\s*0\.82fr\);/,
  );
});

test("builder slots stay keyboard reachable and advertise keyboard placement help", () => {
  assert.match(BUILDER_COMPONENT_SOURCE, /id="builder-workbench-help"/);
  assert.match(BUILDER_COMPONENT_SOURCE, /id="builder-workbench-status"/);
  assert.match(BUILDER_COMPONENT_SOURCE, /aria-describedby="builder-workbench-help builder-workbench-status"/);
  assert.match(BUILDER_COMPONENT_SOURCE, /tabIndex=\{0\}/);
  assert.match(BUILDER_COMPONENT_SOURCE, /event\.key === "Delete" \|\| event\.key === "Backspace"/);
});

test("builder slot focus styles are defined for keyboard and assistive-technology navigation", () => {
  assert.match(GLOBAL_CSS_SOURCE, /\.builder-slot:focus-visible,\s*\.builder-slot:focus-within\s*\{/);
});
