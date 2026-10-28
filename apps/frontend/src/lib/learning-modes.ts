export interface LearningMode {
  /** Verb-first label for the mode. */
  mode: string;
  /** The product surface this maps to. */
  surface: string;
  /** One line: what it is. */
  what: string;
  /** One line: when a learner should reach for it. */
  when: string;
  href: string;
  cta: string;
}

/**
 * The four interactive surfaces, framed so a newcomer can tell them apart in a
 * single read (roadmap P1 "clarify the four interactive surfaces"). Order goes
 * from most passive (Learn) to most active (Build).
 */
export const LEARNING_MODES: LearningMode[] = [
  {
    mode: "Learn",
    surface: "Lessons",
    what: "Read and watch: video, key ideas, notes, and formulas, one lesson at a time.",
    when: "Start here when a topic is new to you.",
    href: "/modules",
    cta: "Open the modules",
  },
  {
    mode: "Practice",
    surface: "Simulations",
    what: "Run interactive models in your browser and watch a concept behave.",
    when: "Use these once you have read a lesson and want intuition, not just words.",
    href: "/simulations",
    cta: "Open simulations",
  },
  {
    mode: "Play",
    surface: "Arena",
    what: "Real-time quiz battles against rivals or an adaptive bot.",
    when: "Come here to test recall under pressure and see where you rank.",
    href: "/arena",
    cta: "Enter the arena",
  },
  {
    mode: "Build",
    surface: "Builder",
    what: "Drag and drop the pieces of a workflow into the right dependency order.",
    when: "Use this to check that you understand how the parts fit together.",
    href: "/builder",
    cta: "Open the builder",
  },
];
