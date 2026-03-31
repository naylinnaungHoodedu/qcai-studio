import assert from "node:assert/strict";
import test from "node:test";

import {
  ASSISTANT_HISTORY_MAX_MESSAGES,
  ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH,
  normalizeAssistantHistory,
} from "../src/lib/assistant-chat";

test("assistant history normalization trims oversized content and keeps the latest window", () => {
  const history = Array.from({ length: 10 }, (_, index) => ({
    role: index % 2 === 0 ? ("user" as const) : ("assistant" as const),
    content: ` message-${index} ${"A".repeat(5000)}`,
  }));

  const normalized = normalizeAssistantHistory(history);

  assert.equal(normalized.length, ASSISTANT_HISTORY_MAX_MESSAGES);
  assert.equal(normalized[0]?.content.startsWith("message-2"), true);
  assert.equal(normalized.at(-1)?.content.startsWith("message-9"), true);
  assert.equal(
    normalized.every((item) => item.content.length <= ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH),
    true,
  );
});
