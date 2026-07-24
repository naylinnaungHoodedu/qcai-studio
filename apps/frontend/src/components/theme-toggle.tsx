"use client";

import { useSyncExternalStore } from "react";

type Theme = "dark" | "light";

// Read the active theme straight from the <html> data-theme attribute (set
// pre-paint by the nonce'd script in layout.tsx). useSyncExternalStore gives a
// stable server snapshot ("dark") and lets React reconcile the client value
// without a hydration warning, and re-renders when the attribute changes.
function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

function getSnapshot(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function getServerSnapshot(): Theme {
  return "dark";
}

// Opt-in light/dark toggle. Dark is the default and remains unchanged; this
// control simply flips the data-theme attribute on <html> and persists it.
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  function toggleTheme() {
    const next: Theme = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem("qcai-theme", next);
    } catch {
      // Ignore storage failures (private mode, disabled storage, etc.).
    }
  }

  const label = theme === "light" ? "Switch to dark theme" : "Switch to light theme";

  return (
    <button
      aria-label={label}
      aria-pressed={theme === "light" ? "true" : "false"}
      className="theme-toggle"
      onClick={toggleTheme}
      title={label}
      type="button"
    >
      <span aria-hidden="true">{theme === "light" ? "☀︎" : "☽"}</span>
    </button>
  );
}
