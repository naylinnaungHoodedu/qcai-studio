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
  if (!videoAsset) {
    return (
      <section className="panel">
        <h2>Lesson Media</h2>
        <p>This lesson uses document-grounded content only.</p>
      </section>
    );
  }

  const videoUrl = `${getClientApiBaseUrl()}${videoAsset.download_url}`;

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Video Lesson</p>
          <h2>{videoAsset.title}</h2>
        </div>
      </div>
      <video
        aria-label={`Video lesson: ${videoAsset.title}`}
        className="lesson-video"
        controls
        preload="metadata"
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
    </section>
  );
}
