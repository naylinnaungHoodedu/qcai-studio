import assert from "node:assert/strict";
import test from "node:test";

import { describeApiError } from "../src/lib/api-errors";

test("api error formatter turns FastAPI validation arrays into actionable assistant copy", () => {
  const message = describeApiError(
    422,
    new Headers(),
    {
      detail: [
        {
          loc: ["body", "history", 1, "content"],
          msg: "String should have at most 4000 characters",
        },
      ],
    },
  );

  assert.equal(message, "The assistant context was too long. Please send the question again.");
});

test("api error formatter turns rate limits into retry guidance", () => {
  const message = describeApiError(
    429,
    new Headers({ "retry-after": "57" }),
    {},
  );

  assert.equal(message, "Too many requests right now. Wait about 57 seconds and try again.");
});
