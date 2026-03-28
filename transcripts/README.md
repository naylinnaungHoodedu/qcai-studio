# Transcript Drops

The `transcripts/` directory is optional source content for time-aligned lesson transcripts.

Current state:

- if no matching transcript JSON exists, the API falls back to curated chapter summaries
- those fallback chapters are now labeled with `transcript_status: "curated_chapter_summary"`
- to unlock aligned transcript panels, drop a JSON file here whose filename matches the video stem

Expected filenames:

- `Quantum Computing and Artificial Intelligence 2025.json`
- `Quantum Computing and Artificial Intelligence 2026.json`
- `Industry Use Cases.json`

Expected JSON shape:

```json
{
  "chapters": [
    {
      "id": "2025-intro",
      "title": "Why Quantum plus AI",
      "timestamp_start": 0,
      "timestamp_end": 71,
      "summary": "Introduces the QC+AI field and frames it through practical hardware limits.",
      "transcript_excerpt": "Aligned transcript text for this span.",
      "transcript_status": "aligned_transcript"
    }
  ]
}
```

An example payload is included in `_example.chapter-transcript.json`.
