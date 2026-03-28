import assert from "node:assert/strict";
import test from "node:test";

import { splitSyllabusAssets } from "../src/lib/syllabus";

test("splitSyllabusAssets keeps cited documents out of the supplemental asset list", () => {
  const { documentAssets, supplementalAssets } = splitSyllabusAssets([
    { id: "doc-1", title: "Proceedings", kind: "document", filename: "proceedings.docx" },
    { id: "video-1", title: "Lecture", kind: "video", filename: "lecture.mp4" },
    { id: "pdf-1", title: "Slides", kind: "pdf", filename: "slides.pdf" },
  ]);

  assert.deepEqual(
    documentAssets.map((asset) => asset.id),
    ["doc-1"],
  );
  assert.deepEqual(
    supplementalAssets.map((asset) => asset.id),
    ["video-1", "pdf-1"],
  );
});
