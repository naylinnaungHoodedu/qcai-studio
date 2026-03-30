import { BuilderSlot } from "./types";

export const BUILDER_CANVAS_WIDTH = 1024;
export const BUILDER_CANVAS_HEIGHT = 620;
export const BUILDER_SLOT_WIDTH = 188;
export const BUILDER_SLOT_HEIGHT = 152;
const BUILDER_CANVAS_PADDING_X = 36;
const BUILDER_CANVAS_PADDING_Y = 32;

type BuilderSlotPosition = {
  x: number;
  y: number;
  leftPercent: string;
  topPercent: string;
};

export type BuilderCanvasLayout = {
  width: number;
  height: number;
  slotWidth: number;
  slotHeight: number;
  positions: Record<string, BuilderSlotPosition>;
};

function projectToRange(
  value: number,
  sourceMin: number,
  sourceMax: number,
  targetMin: number,
  targetMax: number,
): number {
  if (sourceMax === sourceMin) {
    return (targetMin + targetMax) / 2;
  }
  return targetMin + ((value - sourceMin) / (sourceMax - sourceMin)) * (targetMax - targetMin);
}

export function getBuilderCanvasLayout(slots: BuilderSlot[]): BuilderCanvasLayout {
  if (!slots.length) {
    return {
      width: BUILDER_CANVAS_WIDTH,
      height: BUILDER_CANVAS_HEIGHT,
      slotWidth: BUILDER_SLOT_WIDTH,
      slotHeight: BUILDER_SLOT_HEIGHT,
      positions: {},
    };
  }

  const sourceXValues = slots.map((slot) => slot.x);
  const sourceYValues = slots.map((slot) => slot.y);
  const minSourceX = Math.min(...sourceXValues);
  const maxSourceX = Math.max(...sourceXValues);
  const minSourceY = Math.min(...sourceYValues);
  const maxSourceY = Math.max(...sourceYValues);

  const targetMinX = BUILDER_CANVAS_PADDING_X + BUILDER_SLOT_WIDTH / 2;
  const targetMaxX = BUILDER_CANVAS_WIDTH - BUILDER_CANVAS_PADDING_X - BUILDER_SLOT_WIDTH / 2;
  const targetMinY = BUILDER_CANVAS_PADDING_Y + BUILDER_SLOT_HEIGHT / 2;
  const targetMaxY = BUILDER_CANVAS_HEIGHT - BUILDER_CANVAS_PADDING_Y - BUILDER_SLOT_HEIGHT / 2;

  const positions = Object.fromEntries(
    slots.map((slot) => {
      const x = Math.round(
        projectToRange(slot.x, minSourceX, maxSourceX, targetMinX, targetMaxX),
      );
      const y = Math.round(
        projectToRange(slot.y, minSourceY, maxSourceY, targetMinY, targetMaxY),
      );
      return [
        slot.id,
        {
          x,
          y,
          leftPercent: `${((x / BUILDER_CANVAS_WIDTH) * 100).toFixed(2)}%`,
          topPercent: `${((y / BUILDER_CANVAS_HEIGHT) * 100).toFixed(2)}%`,
        },
      ];
    }),
  );

  return {
    width: BUILDER_CANVAS_WIDTH,
    height: BUILDER_CANVAS_HEIGHT,
    slotWidth: BUILDER_SLOT_WIDTH,
    slotHeight: BUILDER_SLOT_HEIGHT,
    positions,
  };
}

export function placeBuilderNode(
  placements: Record<string, string>,
  slotId: string,
  nodeId: string,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const [key, value] of Object.entries(placements)) {
    if (key !== slotId && value !== nodeId) {
      next[key] = value;
    }
  }
  next[slotId] = nodeId;
  return next;
}

export function removeBuilderNode(
  placements: Record<string, string>,
  slotId: string,
): Record<string, string> {
  const next = { ...placements };
  delete next[slotId];
  return next;
}
