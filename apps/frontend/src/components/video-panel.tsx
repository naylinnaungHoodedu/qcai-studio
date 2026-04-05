"use client";

import { useEffect, useRef, useState } from "react";

import { getClientApiBaseUrl } from "@/lib/api";
import { SourceAsset, VideoChapter } from "@/lib/types";

function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${remainder
    .toString()
    .padStart(2, "0")}`;
}

export function VideoPanel({
  videoAsset,
  chapters,
}: {
  videoAsset?: SourceAsset | null;
  chapters: VideoChapter[];
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [activeChapterId, setActiveChapterId] = useState(chapters[0]?.id ?? "");
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"preparing" | "ready" | "error">("preparing");
  const [streamMessage, setStreamMessage] = useState("Preparing authenticated lesson stream.");
  const [refreshToken, setRefreshToken] = useState(0);
  const resolvedVideoUrl =
    videoAsset?.download_url != null ? `${getClientApiBaseUrl()}${videoAsset.download_url}` : null;
  const showStreamRecoveryControls = streamState !== "ready";

  useEffect(() => {
    if (!videoRef.current || chapters.length === 0) {
      return;
    }
    const video = videoRef.current;
    const updateActiveChapter = () => {
      const currentTime = video.currentTime;
      const activeChapter =
        chapters.find(
          (chapter) =>
            currentTime >= chapter.timestamp_start && currentTime < chapter.timestamp_end,
        ) ?? chapters[chapters.length - 1];
      setActiveChapterId(activeChapter?.id ?? "");
    };
    video.addEventListener("timeupdate", updateActiveChapter);
    return () => video.removeEventListener("timeupdate", updateActiveChapter);
  }, [chapters]);

  useEffect(() => {
    if (!resolvedVideoUrl) {
      setVideoUrl(null);
      setStreamState("preparing");
      setStreamMessage("Lesson uses document-grounded content only.");
      return;
    }
    const streamUrl = resolvedVideoUrl;
    let cancelled = false;

    async function bootstrapStream() {
      setVideoUrl(null);
      setStreamState("preparing");
      setStreamMessage("Preparing authenticated lesson stream.");

      try {
        const response = await fetch(streamUrl, {
          method: "HEAD",
          cache: "no-store",
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error(`bootstrap ${response.status}`);
        }
        if (cancelled) {
          return;
        }
        setVideoUrl(streamUrl);
        setStreamState("ready");
        setStreamMessage("Video stream ready. If playback stalls, retry the stream attach.");
      } catch {
        if (cancelled) {
          return;
        }
        setStreamState("error");
        setStreamMessage(
          "The browser could not attach the lesson video. Retry the stream or open the direct asset link.",
        );
      }
    }

    void bootstrapStream();

    return () => {
      cancelled = true;
    };
  }, [refreshToken, resolvedVideoUrl]);

  useEffect(() => {
    if (!videoRef.current || !videoUrl) {
      return;
    }
    videoRef.current.load();
  }, [videoUrl]);

  if (!videoAsset || !resolvedVideoUrl) {
    return (
      <section className="panel">
        <h2>Lesson Media</h2>
        <p>This lesson uses document-grounded content only.</p>
      </section>
    );
  }

  function seekToChapter(chapter: VideoChapter) {
    if (!videoRef.current) {
      return;
    }
    videoRef.current.currentTime = chapter.timestamp_start;
    void videoRef.current.play().catch(() => null);
    setActiveChapterId(chapter.id);
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Video Lesson</p>
          <h2>{videoAsset.title}</h2>
        </div>
      </div>
      <div className="video-panel-grid">
        <div className="stack">
          {showStreamRecoveryControls ? (
            <div className={`video-status-banner ${streamState}`}>
              <p className="eyebrow">Stream status</p>
              <p>{streamMessage}</p>
              <div className="button-row">
                <button
                  className="secondary-button"
                  onClick={() => setRefreshToken((current) => current + 1)}
                  type="button"
                >
                  Retry stream
                </button>
                <a className="secondary-button" href={resolvedVideoUrl} rel="noreferrer" target="_blank">
                  Open direct asset
                </a>
              </div>
            </div>
          ) : (
            <div className="video-ready-indicator" role="status" aria-live="polite">
              <span className="status-pill completed">Stream ready</span>
            </div>
          )}
          <video
            aria-label={`Video lesson: ${videoAsset.title}`}
            className="lesson-video"
            controls
            onError={() => {
              setStreamState("error");
              setStreamMessage(
                "The browser reported a playback error. Retry the stream attach or open the direct asset link.",
              );
            }}
            onLoadedData={() => {
              setStreamState("ready");
            }}
            playsInline
            preload="metadata"
            ref={videoRef}
          >
            {videoUrl ? <source src={videoUrl} type="video/mp4" /> : null}
            <track kind="captions" />
          </video>
          <div className="chapter-list">
            {chapters.map((chapter) => (
              <article className="chapter-card" key={chapter.id}>
                <div className="chapter-stamp">
                  <span>{formatTimestamp(chapter.timestamp_start)}</span>
                  <span>{formatTimestamp(chapter.timestamp_end)}</span>
                </div>
                <div>
                  <h3>{chapter.title}</h3>
                  <p>{chapter.summary}</p>
                  {chapter.transcript_excerpt ? (
                    <p className="muted">{chapter.transcript_excerpt}</p>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </div>

        <aside className="transcript-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Transcript</p>
              <h3>Navigable segments</h3>
            </div>
          </div>
          <ol className="transcript-list">
            {chapters.map((chapter, index) => (
              <li key={chapter.id}>
                <button
                  className={`transcript-segment ${chapter.id === activeChapterId ? "is-active" : ""}`}
                  onClick={() => seekToChapter(chapter)}
                  type="button"
                >
                  <span className="eyebrow">
                    {index + 1}. {formatTimestamp(chapter.timestamp_start)}
                  </span>
                  <strong>{chapter.title}</strong>
                  <p>{chapter.transcript_excerpt || chapter.summary}</p>
                </button>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </section>
  );
}
