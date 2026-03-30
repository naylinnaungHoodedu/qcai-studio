"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CSSProperties, KeyboardEvent, useMemo, useState } from "react";

import {
  fetchBuilderFeed,
  fetchBuilderProfile,
  fetchBuilderScenarios,
  shareBuilderScenario,
  submitBuilderScenario,
} from "@/lib/api";
import { getBuilderCanvasLayout, placeBuilderNode, removeBuilderNode } from "@/lib/builder";
import { BuilderFeedItem, BuilderProfile, BuilderScenario, BuilderSubmissionResult } from "@/lib/types";

type BuilderStudioProps = {
  initialScenarios?: BuilderScenario[];
  initialProfile?: BuilderProfile | null;
  initialFeed?: BuilderFeedItem[];
};

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function formatDateLabel(value: string): string {
  return new Date(value).toLocaleString();
}

function formatFeedAuthorLabel(userId: string): string {
  const suffix = userId.replace(/[^a-zA-Z0-9]/g, "").slice(-4).toUpperCase();
  return suffix ? `Learner ${suffix}` : "Learner";
}

function cx(...tokens: Array<string | false | null | undefined>): string {
  return tokens.filter(Boolean).join(" ");
}

export function BuilderStudio({
  initialScenarios = [],
  initialProfile = null,
  initialFeed = [],
}: BuilderStudioProps) {
  const queryClient = useQueryClient();
  const [selectedScenarioSlug, setSelectedScenarioSlug] = useState("");
  const [placements, setPlacements] = useState<Record<string, string>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [shareCaption, setShareCaption] = useState("Built a clean dependency graph under pressure.");
  const [lastResult, setLastResult] = useState<BuilderSubmissionResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const scenariosQuery = useQuery({
    queryKey: ["builder-scenarios"],
    queryFn: fetchBuilderScenarios,
    initialData: initialScenarios,
  });
  const profileQuery = useQuery({
    queryKey: ["builder-profile"],
    queryFn: fetchBuilderProfile,
    initialData: initialProfile ?? undefined,
  });
  const feedQuery = useQuery({
    queryKey: ["builder-feed"],
    queryFn: () => fetchBuilderFeed(),
    initialData: initialFeed,
  });

  const scenarios = useMemo(() => scenariosQuery.data ?? [], [scenariosQuery.data]);
  const scenarioMap = useMemo(() => new Map(scenarios.map((item) => [item.slug, item])), [scenarios]);
  const activeScenarioSlug =
    selectedScenarioSlug && scenarioMap.has(selectedScenarioSlug)
      ? selectedScenarioSlug
      : (scenarios.find((item) => item.unlocked && !item.completed) ?? scenarios[0])?.slug ?? "";
  const selectedScenario = scenarioMap.get(activeScenarioSlug) ?? scenarios[0];
  const workbenchTitle = selectedScenario?.title ?? (scenarios.length ? scenarios[0].title : "No scenario available");
  const selectedNode =
    selectedNodeId && selectedScenario
      ? selectedScenario.nodes.find((node) => node.id === selectedNodeId) ?? null
      : null;
  const canvasLayout = getBuilderCanvasLayout(selectedScenario?.slots ?? []);
  const canvasStyle = {
    width: `${canvasLayout.width}px`,
    height: `${canvasLayout.height}px`,
    ["--builder-slot-width" as string]: `${canvasLayout.slotWidth}px`,
    ["--builder-slot-height" as string]: `${canvasLayout.slotHeight}px`,
  } as CSSProperties;

  const submitMutation = useMutation({
    mutationFn: ({ slug, map }: { slug: string; map: Record<string, string> }) => submitBuilderScenario(slug, map),
    onSuccess: (result) => {
      setLastResult(result);
      setErrorMessage(null);
      void queryClient.invalidateQueries({ queryKey: ["builder-scenarios"] });
      void queryClient.invalidateQueries({ queryKey: ["builder-profile"] });
      if (result.completed) {
        setShareCaption(`Completed ${selectedScenario?.title ?? "the dependency graph"} with a clean circuit.`);
      }
    },
    onError: (error) => {
      setErrorMessage(toErrorMessage(error, "Could not score the builder run."));
    },
  });

  const shareMutation = useMutation({
    mutationFn: ({ slug, caption, map }: { slug: string; caption: string; map: Record<string, string> }) =>
      shareBuilderScenario(slug, caption, map),
    onSuccess: () => {
      setErrorMessage(null);
      void queryClient.invalidateQueries({ queryKey: ["builder-feed"] });
      void queryClient.invalidateQueries({ queryKey: ["builder-profile"] });
    },
    onError: (error) => {
      setErrorMessage(toErrorMessage(error, "Could not share this learning map."));
    },
  });

  const placedNodeIds = useMemo(() => new Set(Object.values(placements)), [placements]);
  const availableNodes = selectedScenario
    ? selectedScenario.nodes.filter((node) => !placedNodeIds.has(node.id))
    : [];

  function setScenario(nextScenario: BuilderScenario) {
    if (!nextScenario.unlocked) {
      return;
    }
    setSelectedScenarioSlug(nextScenario.slug);
    setPlacements({});
    setSelectedNodeId(null);
    setLastResult(null);
    setErrorMessage(null);
  }

  function handlePlacement(slotId: string, nodeId: string) {
    setPlacements((current) => placeBuilderNode(current, slotId, nodeId));
    setSelectedNodeId(null);
    setLastResult(null);
    setErrorMessage(null);
  }

  function removePlacement(slotId: string) {
    setPlacements((current) => removeBuilderNode(current, slotId));
    setLastResult(null);
    setErrorMessage(null);
  }

  function resetBoard() {
    setPlacements({});
    setSelectedNodeId(null);
    setLastResult(null);
    setErrorMessage(null);
  }

  function handleSlotKeyDown(event: KeyboardEvent<HTMLDivElement>, slotId: string) {
    if (!selectedNodeId) {
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    handlePlacement(slotId, selectedNodeId);
  }

  function checkCircuit() {
    if (!selectedScenario) {
      return;
    }
    submitMutation.mutate({ slug: selectedScenario.slug, map: placements });
  }

  function shareMap() {
    if (!selectedScenario || !shareCaption.trim()) {
      return;
    }
    shareMutation.mutate({ slug: selectedScenario.slug, caption: shareCaption.trim(), map: placements });
  }

  return (
    <div className="page-stack">
      <section className="section-block builder-hero">
        <div className="section-heading">
          <p className="eyebrow">Game 2</p>
          <h1>Microlearning Drag-and-Drop Builder</h1>
          <p>
            Construct dependency graphs as puzzle circuits. Each completed map unlocks the next engineering challenge,
            updates your streak, and can be published into the shared feed.
          </p>
        </div>
        <div className="builder-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Total points</span>
            <strong>{profileQuery.data?.total_points ?? 0}</strong>
            <p>myCred-style progression without leaving the learning flow.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Current streak</span>
            <strong>{profileQuery.data?.current_streak ?? 0}</strong>
            <p>Consecutive completed circuits before the first miss.</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Course builder progress</span>
            <strong>{profileQuery.data?.completion_percent ?? 0}%</strong>
            <p>
              {profileQuery.data?.completed_scenarios ?? 0} of {scenarios.length || 0} scenarios fully solved.
            </p>
          </article>
        </div>
      </section>

      <div className="game-grid builder-top-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Scenario ladder</p>
              <h2>Unlocked circuits</h2>
            </div>
          </div>
          <div className="builder-scenario-list">
            {scenarios.map((scenario) => (
              <button
                className={cx(
                  "builder-scenario-card",
                  scenario.slug === activeScenarioSlug && "is-selected",
                  !scenario.unlocked && "is-locked",
                )}
                disabled={!scenario.unlocked}
                key={scenario.slug}
                onClick={() => setScenario(scenario)}
                type="button"
              >
                <span className="eyebrow">{scenario.domain}</span>
                <strong>{scenario.title}</strong>
                <p>{scenario.summary}</p>
                <p className="muted">
                  {scenario.completed ? "Completed" : scenario.unlocked ? "Unlocked" : "Locked"} | best{" "}
                  {scenario.best_completion_percent}%
                </p>
              </button>
            ))}
          </div>
        </section>

        <section className="panel builder-workbench">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Workbench</p>
              <h2>{workbenchTitle}</h2>
            </div>
            <div className="button-row">
              <span className="status-pill in_progress">{selectedScenario?.domain ?? "..."}</span>
              <span className="score-pill">{selectedScenario?.points_reward ?? 0} bonus points</span>
            </div>
          </div>
          <div className="builder-workbench-toolbar">
            <p className="muted">
              Drag concepts into the circuit, or tap a concept and then tap a step. On smaller screens, swipe across
              the canvas to inspect the full loop before scoring it.
            </p>
            <div className="builder-workbench-pills">
              <span className="prompt-pill">
                {Object.keys(placements).length} / {selectedScenario?.slots.length ?? 0} placed
              </span>
              <span className={cx("prompt-pill", selectedNode && "is-armed")}>
                {selectedNode ? `Selected: ${selectedNode.label}` : "Tap a concept to arm placement"}
              </span>
            </div>
          </div>

          <div className="builder-grid">
            <div className="builder-canvas-frame">
              <div className="builder-canvas-scroll">
                <div className="builder-canvas" onDragOver={(event) => event.preventDefault()} style={canvasStyle}>
                  {selectedScenario ? (
                    <>
                      <svg
                        className="builder-lines"
                        preserveAspectRatio="none"
                        viewBox={`0 0 ${canvasLayout.width} ${canvasLayout.height}`}
                      >
                        {selectedScenario.connections.map((connection) => {
                          const fromSlot = canvasLayout.positions[connection.from_slot];
                          const toSlot = canvasLayout.positions[connection.to_slot];
                          if (!fromSlot || !toSlot) {
                            return null;
                          }
                          return (
                            <line
                              key={`${connection.from_slot}-${connection.to_slot}`}
                              x1={fromSlot.x}
                              y1={fromSlot.y}
                              x2={toSlot.x}
                              y2={toSlot.y}
                            />
                          );
                        })}
                      </svg>
                      {selectedScenario.slots.map((slot) => {
                        const nodeId = placements[slot.id];
                        const node = selectedScenario.nodes.find((item) => item.id === nodeId);
                        const slotIncorrect = lastResult?.incorrect_slots.includes(slot.id) ?? false;
                        const slotCorrect =
                          Boolean(node) && !slotIncorrect && lastResult?.scenario_slug === selectedScenario.slug;
                        const slotPosition = canvasLayout.positions[slot.id];
                        return (
                          <div
                            aria-label={
                              selectedNode
                                ? `Place ${selectedNode.label} in ${slot.label}`
                                : `${slot.label}. ${slot.description}`
                            }
                            className={cx(
                              "builder-slot",
                              selectedNode && "is-armed",
                              Boolean(node) && "has-node",
                              slotIncorrect && "is-incorrect",
                              slotCorrect && lastResult?.completed && "is-correct",
                            )}
                            key={slot.id}
                            onClick={() => {
                              if (selectedNodeId) {
                                handlePlacement(slot.id, selectedNodeId);
                              }
                            }}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={(event) => {
                              event.preventDefault();
                              const droppedNodeId = event.dataTransfer.getData("text/plain");
                              if (droppedNodeId) {
                                handlePlacement(slot.id, droppedNodeId);
                              }
                            }}
                            onKeyDown={(event) => handleSlotKeyDown(event, slot.id)}
                            role="button"
                            style={{
                              left: slotPosition?.leftPercent,
                              top: slotPosition?.topPercent,
                            }}
                            tabIndex={selectedNodeId ? 0 : -1}
                          >
                            <span className="eyebrow">{slot.label}</span>
                            <strong>{slot.description}</strong>
                            {node ? (
                              <button
                                className="builder-node placed"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  removePlacement(slot.id);
                                }}
                                style={{ backgroundColor: node.color }}
                                type="button"
                              >
                                {node.label}
                              </button>
                            ) : selectedNode ? (
                              <p className="muted">Tap to place {selectedNode.label}</p>
                            ) : (
                              <p className="muted">Drop a concept here</p>
                            )}
                          </div>
                        );
                      })}
                    </>
                  ) : (
                    <article className="empty-state-card">
                      <strong>No scenario available yet</strong>
                      <p className="muted">
                        The builder could not load an unlocked scenario for this request. Refresh the page to retry the
                        current guest session.
                      </p>
                    </article>
                  )}
                </div>
              </div>
            </div>

            <div className="stack builder-side-stack">
              <div className="panel inset-panel builder-selection-card">
                <p className="eyebrow">Placement mode</p>
                {selectedNode ? (
                  <>
                    <strong>{selectedNode.label}</strong>
                    <p className="muted">
                      Tap a highlighted step to place this concept, or drag it directly into the circuit.
                    </p>
                    <div className="button-row">
                      <button className="secondary-button" onClick={() => setSelectedNodeId(null)} type="button">
                        Clear selection
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="muted">
                    Choose a concept from the tray to activate touch-friendly placement. Drag-and-drop remains available
                    on desktop.
                  </p>
                )}
              </div>

              <div className="panel inset-panel">
                <p className="eyebrow">Concept tray</p>
                <div className="builder-node-tray">
                  {availableNodes.map((node) => (
                    <button
                      aria-pressed={selectedNodeId === node.id}
                      className={cx("builder-node", selectedNodeId === node.id && "is-selected")}
                      draggable
                      key={node.id}
                      onClick={() => setSelectedNodeId((current) => (current === node.id ? null : node.id))}
                      onDragStart={(event) => event.dataTransfer.setData("text/plain", node.id)}
                      style={{ backgroundColor: node.color }}
                      type="button"
                    >
                      <strong>{node.label}</strong>
                      <span>{node.description}</span>
                    </button>
                  ))}
                  {!availableNodes.length ? <p className="muted">All concepts have been placed on the graph.</p> : null}
                </div>
              </div>

              <div className="button-row">
                <button className="primary-button" disabled={submitMutation.isPending} onClick={checkCircuit} type="button">
                  {submitMutation.isPending ? "Scoring..." : "Check circuit"}
                </button>
                <button className="secondary-button" onClick={resetBoard} type="button">
                  Reset board
                </button>
              </div>

              {lastResult ? (
                <article className="builder-result-card">
                  <p className="eyebrow">Latest result</p>
                  <h3>
                    {lastResult.completed ? "Circuit complete" : "Partial circuit"} | {lastResult.completion_percent}%
                  </h3>
                  <p>
                    {lastResult.correct_slots} / {lastResult.total_slots} slots matched | +{lastResult.points_earned} points
                  </p>
                  <p className="muted">
                    Streak {lastResult.current_streak} | badges {lastResult.badges.join(", ") || "none yet"}
                  </p>
                  {lastResult.unlocked_next_slug ? (
                    <p className="muted">Unlocked next scenario: {lastResult.unlocked_next_slug}</p>
                  ) : null}
                </article>
              ) : null}

              <div className="panel inset-panel">
                <p className="eyebrow">Share this map</p>
                <textarea
                  className="note-input"
                  onChange={(event) => setShareCaption(event.target.value)}
                  rows={3}
                  value={shareCaption}
                />
                <div className="button-row">
                  <button
                    className="secondary-button"
                    disabled={shareMutation.isPending || !(lastResult?.completed || selectedScenario?.completed)}
                    onClick={shareMap}
                    type="button"
                  >
                    {shareMutation.isPending ? "Sharing..." : "Publish to feed"}
                  </button>
                </div>
              </div>

              {errorMessage ? <p className="muted">{errorMessage}</p> : null}
            </div>
          </div>
        </section>
      </div>

      <div className="game-grid">
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Badge rack</p>
              <h2>Retention loop</h2>
            </div>
          </div>
          <div className="builder-badge-row">
            {(profileQuery.data?.badges ?? []).map((badge) => (
              <span className="status-pill completed" key={badge}>
                {badge}
              </span>
            ))}
            {!profileQuery.data?.badges.length ? <p className="muted">Complete and share maps to unlock badges.</p> : null}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Social feed</p>
              <h2>Published learning maps</h2>
            </div>
          </div>
          <div className="stack">
            {(feedQuery.data ?? []).map((item: BuilderFeedItem) => (
              <article className="citation-card" key={item.id}>
                <strong>{item.scenario_title}</strong>
                <p className="muted">
                  {formatFeedAuthorLabel(item.user_id)} | {item.completion_percent}% | {formatDateLabel(item.created_at)}
                </p>
                <p>{item.caption}</p>
              </article>
            ))}
            {!feedQuery.data?.length ? (
              <article className="empty-state-card">
                <strong>No shared maps yet</strong>
                <p className="muted">
                  This deployment has not accumulated community builder activity yet. Solve a circuit and publish the
                  first shared learning map.
                </p>
                <div className="button-row">
                  <button className="primary-button" onClick={checkCircuit} type="button">
                    Check current circuit
                  </button>
                  <Link className="secondary-button" href="/account">
                    Open account options
                  </Link>
                </div>
              </article>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
