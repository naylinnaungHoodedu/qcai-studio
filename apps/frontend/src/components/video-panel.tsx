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

  if (!videoAsset) {
    return (
      <section className="panel">
        <h2>Lesson Media</h2>
        <p>This lesson uses document-grounded content only.</p>
      </section>
    );
  }

  const videoUrl = `${getClientApiBaseUrl()}${videoAsset.download_url}`;

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
          <video
            aria-label={`Video lesson: ${videoAsset.title}`}
            className="lesson-video"
            controls
            preload="metadata"
            ref={videoRef}
            src={videoUrl}
          >
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
          <div className="transcript-list" role="list">
            {chapters.map((chapter, index) => (
              <button
                className={`transcript-segment ${chapter.id === activeChapterId ? "is-active" : ""}`}
                key={chapter.id}
                onClick={() => seekToChapter(chapter)}
                type="button"
              >
                <span className="eyebrow">
                  {index + 1}. {formatTimestamp(chapter.timestamp_start)}
                </span>
                <strong>{chapter.title}</strong>
                <p>{chapter.transcript_excerpt || chapter.summary}</p>
              </button>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}
