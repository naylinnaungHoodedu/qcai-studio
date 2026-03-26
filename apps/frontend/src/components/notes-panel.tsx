"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { createLessonNote, fetchLessonNotes, postAnalyticsEvent } from "@/lib/api";

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function NotesPanel({ lessonSlug }: { lessonSlug: string }) {
  const [value, setValue] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const notesQuery = useQuery({
    queryKey: ["notes", lessonSlug],
    queryFn: () => fetchLessonNotes(lessonSlug),
  });

  const mutation = useMutation({
    mutationFn: (body: string) => createLessonNote(lessonSlug, body),
    onSuccess: (_, body) => {
      setValue("");
      setSaveError(null);
      void queryClient.invalidateQueries({ queryKey: ["notes", lessonSlug] });
      void postAnalyticsEvent("lesson_note_created", lessonSlug, {
        note_length: body.length,
      }).catch(() => null);
    },
    onError: (error) => {
      setSaveError(toErrorMessage(error, "Could not save the note."));
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!value.trim()) {
      return;
    }
    mutation.mutate(value.trim());
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Notes</p>
          <h2>Linked lesson notes</h2>
        </div>
      </div>
      <form className="stack" onSubmit={handleSubmit}>
        <textarea
          className="note-input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Capture a hardware bottleneck, architectural pattern, or question you want to revisit."
          rows={5}
        />
        <button className="primary-button" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : "Save note"}
        </button>
      </form>
      <div className="stack">
        {saveError ? <p className="muted">{saveError}</p> : null}
        {notesQuery.isLoading ? <p className="muted">Loading saved notes...</p> : null}
        {notesQuery.isError ? (
          <p className="muted">{toErrorMessage(notesQuery.error, "Could not load notes right now.")}</p>
        ) : null}
        {(notesQuery.data ?? []).map((note) => (
          <article key={note.id} className="note-card">
            <p>{note.body}</p>
            <span>{new Date(note.created_at).toLocaleString()}</span>
          </article>
        ))}
        {notesQuery.data?.length === 0 ? (
          <p className="muted">No notes yet. Save one as you study the lesson.</p>
        ) : null}
      </div>
    </section>
  );
}
