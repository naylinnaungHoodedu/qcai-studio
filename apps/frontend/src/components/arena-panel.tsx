"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { fetchArenaLeaderboard, fetchArenaProfile, fetchArenaStatus } from "@/lib/api";
import { ArenaLeaderboardEntry, ArenaProfile } from "@/lib/types";

type ArenaPanelProps = {
  apiBaseUrl: string;
};

type ArenaMessage = {
  type: string;
  [key: string]: unknown;
};

type ArenaChallenge = {
  id: string;
  title: string;
  topic: string;
  difficulty: number;
  kind: string;
  scenario: string;
  prompt: string;
  options: string[];
  starter_code?: string | null;
};

type ArenaPlayerScore = {
  player_id: string;
  display_name: string;
  score: number;
  correct_answers: number;
  submitted_answers: number;
  adaptive_level: number;
  is_self?: boolean;
  is_bot?: boolean;
};

type ArenaRoundResult = {
  round_number: number;
  correct_answer: string;
  explanation: string;
  answer_state: Array<{
    player_id: string;
    display_name: string;
    answer: string;
    correct: boolean;
    score_delta: number;
    time_taken_ms: number;
    is_bot?: boolean;
  }>;
};

const PLAYER_ID_STORAGE_KEY = "qcai-arena-player-id";
const PLAYER_NAME_STORAGE_KEY = "qcai-arena-player-name";

function ensurePlayerId(): string {
  const existing = window.localStorage.getItem(PLAYER_ID_STORAGE_KEY);
  if (existing) {
    return existing;
  }
  const nextId = `arena-${crypto.randomUUID().slice(0, 8)}`;
  window.localStorage.setItem(PLAYER_ID_STORAGE_KEY, nextId);
  return nextId;
}

function ensureDisplayName(): string {
  const existing = window.localStorage.getItem(PLAYER_NAME_STORAGE_KEY);
  if (existing) {
    return existing;
  }
  const nextName = "Hybrid Challenger";
  window.localStorage.setItem(PLAYER_NAME_STORAGE_KEY, nextName);
  return nextName;
}

function toWebSocketUrl(apiBaseUrl: string): string {
  const url = new URL(apiBaseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  if (typeof window !== "undefined" && ["api", "0.0.0.0"].includes(url.hostname)) {
    url.hostname = window.location.hostname;
  }
  url.pathname = "/arena/ws";
  url.search = "";
  return url.toString();
}

function formatMillis(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(1)}s`;
}

function formatConnectionState(state: string): string {
  if (state === "queued") {
    return "Queued";
  }
  if (state === "live") {
    return "Live match";
  }
  if (state === "complete") {
    return "Match complete";
  }
  if (state === "connecting") {
    return "Connecting";
  }
  return "Idle";
}

export function ArenaPanel({ apiBaseUrl }: ArenaPanelProps) {
  const queryClient = useQueryClient();
  const socketRef = useRef<WebSocket | null>(null);
  const [playerId] = useState(() => (typeof window === "undefined" ? "" : ensurePlayerId()));
  const [displayName, setDisplayName] = useState(() => (typeof window === "undefined" ? "" : ensureDisplayName()));
  const [mode, setMode] = useState<"ranked" | "bot">("bot");
  const [connectionState, setConnectionState] = useState("idle");
  const [statusMessage, setStatusMessage] = useState("Pick a mode and enter the arena.");
  const [players, setPlayers] = useState<ArenaPlayerScore[]>([]);
  const [challenge, setChallenge] = useState<ArenaChallenge | null>(null);
  const [roundNumber, setRoundNumber] = useState(0);
  const [roundsTotal, setRoundsTotal] = useState(5);
  const [difficultyBand, setDifficultyBand] = useState(1);
  const [roundStartedAt, setRoundStartedAt] = useState<number | null>(null);
  const [roundDurationSeconds, setRoundDurationSeconds] = useState(0);
  const [clockTick, setClockTick] = useState(() => Date.now());
  const [pendingAnswer, setPendingAnswer] = useState("");
  const [roundResult, setRoundResult] = useState<ArenaRoundResult | null>(null);
  const [matchSummary, setMatchSummary] = useState<ArenaMessage | null>(null);

  useEffect(() => {
    if (!displayName) {
      return;
    }
    window.localStorage.setItem(PLAYER_NAME_STORAGE_KEY, displayName);
  }, [displayName]);

  useEffect(() => {
    if (!roundStartedAt || !roundDurationSeconds) {
      return;
    }
    const interval = window.setInterval(() => {
      setClockTick(Date.now());
    }, 250);
    return () => window.clearInterval(interval);
  }, [roundStartedAt, roundDurationSeconds]);

  useEffect(() => {
    return () => {
      socketRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!challenge || challenge.kind !== "mcq") {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      const index = Number(event.key) - 1;
      if (Number.isNaN(index) || index < 0 || index >= challenge.options.length) {
        return;
      }
      setPendingAnswer(challenge.options[index]);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [challenge]);

  const leaderboardQuery = useQuery({
    queryKey: ["arena-leaderboard"],
    queryFn: fetchArenaLeaderboard,
    refetchInterval: 15_000,
  });

  const statusQuery = useQuery({
    queryKey: ["arena-status"],
    queryFn: fetchArenaStatus,
    refetchInterval: 5_000,
  });

  const profileQuery = useQuery({
    queryKey: ["arena-profile", playerId],
    queryFn: () => fetchArenaProfile(playerId),
    enabled: Boolean(playerId),
  });

  const sortedLeaderboard = useMemo(() => leaderboardQuery.data ?? [], [leaderboardQuery.data]);
  const currentProfile = profileQuery.data;
  const timeRemaining = useMemo(() => {
    if (!roundStartedAt || !roundDurationSeconds) {
      return 0;
    }
    return Math.max(0, Math.ceil(roundStartedAt + roundDurationSeconds - clockTick / 1000));
  }, [clockTick, roundDurationSeconds, roundStartedAt]);

  function openSocket(nextMode: "ranked" | "bot") {
    if (!playerId || !displayName.trim()) {
      return;
    }
    socketRef.current?.close();
    const url = new URL(toWebSocketUrl(apiBaseUrl));
    url.searchParams.set("player_id", playerId);
    url.searchParams.set("display_name", displayName.trim());
    url.searchParams.set("mode", nextMode);
    const socket = new WebSocket(url);
    socketRef.current = socket;
    setMode(nextMode);
    setConnectionState("connecting");
    setStatusMessage(nextMode === "ranked" ? "Joining the ranked queue..." : "Launching an adaptive bot match...");
    setChallenge(null);
    setRoundResult(null);
    setMatchSummary(null);
    setPlayers([]);
    setPendingAnswer("");

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as ArenaMessage;
      if (message.type === "connected") {
        setStatusMessage(`Connected as ${message.display_name as string}.`);
        return;
      }
      if (message.type === "queue_status") {
        setConnectionState("queued");
        const position = message.position ? ` Queue position ${message.position as number}.` : "";
        setStatusMessage(`${(message.message as string) ?? "Waiting for the next challenger."}${position}`);
        return;
      }
      if (message.type === "match_found") {
        setConnectionState("live");
        setPlayers((message.players as ArenaPlayerScore[]) ?? []);
        setDifficultyBand((message.difficulty_band as number) ?? 1);
        setRoundsTotal((message.rounds_total as number) ?? 5);
        setStatusMessage(`Match ready. Difficulty band ${message.difficulty_band as number}.`);
        return;
      }
      if (message.type === "challenge") {
        setChallenge(message.challenge as ArenaChallenge);
        setPlayers((message.players as ArenaPlayerScore[]) ?? []);
        setRoundNumber((message.round_number as number) ?? 1);
        setRoundsTotal((message.rounds_total as number) ?? 5);
        setDifficultyBand((message.difficulty_band as number) ?? 1);
        setRoundStartedAt((message.round_started_at as number) ?? null);
        setRoundDurationSeconds((message.round_duration_seconds as number) ?? 0);
        setPendingAnswer("");
        setRoundResult(null);
        setStatusMessage("Round live. Submit before the timer expires.");
        return;
      }
      if (message.type === "round_result") {
        setRoundResult({
          round_number: (message.round_number as number) ?? 0,
          correct_answer: message.correct_answer as string,
          explanation: message.explanation as string,
          answer_state: (message.answer_state as ArenaRoundResult["answer_state"]) ?? [],
        });
        setPlayers((message.players as ArenaPlayerScore[]) ?? []);
        setDifficultyBand((message.next_difficulty_band as number) ?? difficultyBand);
        setChallenge(null);
        setRoundStartedAt(null);
        setRoundDurationSeconds(0);
        setStatusMessage("Round graded. Reviewing the explanation before the next challenge.");
        return;
      }
      if (message.type === "match_complete") {
        setMatchSummary(message);
        setChallenge(null);
        setRoundStartedAt(null);
        setRoundDurationSeconds(0);
        setPlayers((message.players as ArenaPlayerScore[]) ?? []);
        setConnectionState("complete");
        setStatusMessage("Match complete. XP and adaptive rating updated.");
        void queryClient.invalidateQueries({ queryKey: ["arena-leaderboard"] });
        void queryClient.invalidateQueries({ queryKey: ["arena-profile", playerId] });
        void queryClient.invalidateQueries({ queryKey: ["arena-status"] });
      }
    };

    socket.onclose = () => {
      setConnectionState((current) => (current === "complete" ? current : "idle"));
      void queryClient.invalidateQueries({ queryKey: ["arena-status"] });
    };
  }

  function submitAnswer(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN || !pendingAnswer.trim()) {
      return;
    }
    socketRef.current.send(JSON.stringify({ type: "answer", answer: pendingAnswer.trim() }));
    setStatusMessage("Answer locked in. Waiting for the round to resolve.");
  }

  function renderProfile(profile?: ArenaProfile) {
    if (!profile) {
      return <p className="muted">Arena profile is loading.</p>;
    }
    return (
      <div className="stack">
        <div className="arena-metric-grid">
          <article className="metric-card">
            <span className="eyebrow">Rank</span>
            <strong>{profile.rank_label}</strong>
            <p>{profile.xp} XP</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Adaptive level</span>
            <strong>{profile.adaptive_level}</strong>
            <p>Skill rating {profile.skill_rating}</p>
          </article>
          <article className="metric-card">
            <span className="eyebrow">Recent form</span>
            <strong>{profile.recent_form}</strong>
            <p>{profile.matches_played} matches recorded</p>
          </article>
        </div>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="section-block arena-hero">
        <div className="section-heading">
          <p className="eyebrow">Game 1</p>
          <h1>AI &amp; Quantum Challenge Arena</h1>
          <p>
            Enter real-time ranked or bot-backed battles across AI/ML and quantum systems scenarios. Difficulty adapts
            to the match band, XP is persisted, and the leaderboard updates from live results.
          </p>
        </div>
        <div className="arena-control-bar">
          <label className="arena-name-field">
            <span className="eyebrow">Arena handle</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={40} />
          </label>
          <div className="button-row">
            <button className="primary-button" onClick={() => openSocket("ranked")} type="button">
              Join ranked
            </button>
            <button className="secondary-button" onClick={() => openSocket("bot")} type="button">
              Practice vs bot
            </button>
          </div>
          <p className="muted">
            Status: <strong>{formatConnectionState(connectionState)}</strong>. Mode <strong>{mode}</strong>.{" "}
            {statusMessage}
          </p>
          <div className="arena-presence-bar">
            <span className="status-pill">Queue {statusQuery.data?.queue_size ?? 0}</span>
            <span className="status-pill">Live matches {statusQuery.data?.active_matches ?? 0}</span>
            <span className="status-pill">Connected {statusQuery.data?.connected_players ?? 0}</span>
          </div>
        </div>
      </section>

      <div className="game-grid">
        <section className="panel arena-stage">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Battle stage</p>
              <h2>
                Round {roundNumber || 0} / {roundsTotal}
              </h2>
            </div>
            <div className="button-row">
              <span className="status-pill in_progress">Band {difficultyBand}</span>
              {challenge ? <span className="score-pill">{timeRemaining}s left</span> : null}
            </div>
          </div>

          <div className="arena-scoreboard">
            {players.map((player) => (
              <article className={`arena-score-card ${player.is_self ? "is-self" : ""}`} key={player.player_id}>
                <span className="eyebrow">{player.is_bot ? "AI rival" : player.is_self ? "You" : "Opponent"}</span>
                <strong>{player.display_name}</strong>
                <p>Score {player.score} | correct {player.correct_answers}</p>
              </article>
            ))}
          </div>

          {challenge ? (
            <article className="arena-challenge-card">
              <p className="eyebrow">
                {challenge.topic} | difficulty {challenge.difficulty}
              </p>
              <h3>{challenge.title}</h3>
              <p>{challenge.scenario}</p>
              <p className="arena-prompt">{challenge.prompt}</p>
              {challenge.kind === "mcq" ? (
                <>
                  <p className="muted">Keyboard shortcut: press 1-4 to select an answer.</p>
                  <div className="choice-list">
                    {challenge.options.map((option) => (
                      <button
                        className={`choice-item arena-choice ${pendingAnswer === option ? "selected" : ""}`}
                        key={option}
                        onClick={() => setPendingAnswer(option)}
                        type="button"
                      >
                        <span>{option}</span>
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <form className="stack" onSubmit={submitAnswer}>
                  <pre className="arena-code">{challenge.starter_code}</pre>
                  <textarea
                    className="note-input"
                    onChange={(event) => setPendingAnswer(event.target.value)}
                    placeholder="Enter the missing token or expression"
                    rows={4}
                    value={pendingAnswer}
                  />
                  <button className="primary-button" type="submit">
                    Submit code answer
                  </button>
                </form>
              )}
              {challenge.kind === "mcq" ? (
                <div className="button-row">
                  <button className="primary-button" onClick={() => submitAnswer()} type="button">
                    Lock answer
                  </button>
                </div>
              ) : null}
            </article>
          ) : null}

          {roundResult ? (
            <article className="arena-result-card">
              <p className="eyebrow">Round {roundResult.round_number} review</p>
              <h3>Correct answer: {roundResult.correct_answer}</h3>
              <p>{roundResult.explanation}</p>
              <div className="stack">
                {roundResult.answer_state.map((entry) => (
                  <div className="citation-card" key={entry.player_id}>
                    <strong>{entry.display_name}</strong>
                    <p className="muted">
                      {entry.correct ? "Correct" : "Missed"} | delta {entry.score_delta} | {formatMillis(entry.time_taken_ms)}
                    </p>
                    <p>{entry.answer || "No answer submitted."}</p>
                  </div>
                ))}
              </div>
            </article>
          ) : null}

          {matchSummary ? (
            <article className="arena-result-card">
              <p className="eyebrow">Match complete</p>
              <h3>XP settlement</h3>
              <div className="stack">
                {((matchSummary.xp_updates as ArenaMessage[]) ?? []).map((update) => (
                  <div className="citation-card" key={update.player_id as string}>
                    <strong>{update.display_name as string}</strong>
                    <p className="muted">
                      +{update.xp_delta as number} XP | rating {update.skill_rating as number} | band{" "}
                      {update.adaptive_level as number}
                    </p>
                    <p>{update.rank_label as string}</p>
                  </div>
                ))}
              </div>
            </article>
          ) : null}
        </section>

        <div className="stack">
          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Arena profile</p>
                <h2>Persistent progression</h2>
              </div>
            </div>
            {renderProfile(currentProfile)}
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Leaderboard</p>
                <h2>XP ladder</h2>
              </div>
            </div>
            <div className="stack">
              {sortedLeaderboard.map((entry: ArenaLeaderboardEntry, index) => (
                <article className="arena-leaderboard-row" key={entry.player_id}>
                  <strong>
                    #{index + 1} {entry.display_name}
                  </strong>
                  <p className="muted">
                    {entry.rank_label} | {entry.xp} XP | win rate {entry.win_rate_percent}%
                  </p>
                </article>
              ))}
              {!sortedLeaderboard.length ? (
                <article className="empty-state-card">
                  <strong>No ranked results yet</strong>
                  <p className="muted">
                    The arena leaderboard is still empty on this deployment. Join ranked play or complete a bot match to seed the first visible results.
                  </p>
                  <div className="button-row">
                    <button className="primary-button" onClick={() => openSocket("ranked")} type="button">
                      Start ranked play
                    </button>
                    <Link className="secondary-button" href="/account">
                      Review account options
                    </Link>
                  </div>
                </article>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
