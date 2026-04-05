import assert from "node:assert/strict";
import test from "node:test";

import { postPublicWebVital, submitSupportRequest } from "../src/lib/api";

type BrowserGlobals = typeof globalThis & {
  window?: unknown;
  document?: { cookie: string };
};

function withBrowserCookies(cookie: string) {
  const browserGlobals = globalThis as BrowserGlobals;
  const originalWindow = browserGlobals.window;
  const originalDocument = browserGlobals.document;

  browserGlobals.window = {};
  browserGlobals.document = { cookie };

  return () => {
    if (originalWindow === undefined) {
      delete browserGlobals.window;
    } else {
      browserGlobals.window = originalWindow;
    }

    if (originalDocument === undefined) {
      delete browserGlobals.document;
    } else {
      browserGlobals.document = originalDocument;
    }
  };
}

test("public web-vitals requests keep guest CSRF protection in browser mode", async () => {
  const cleanupBrowser = withBrowserCookies(
    "qcai_guest_id=guest-123e4567-e89b-12d3-a456-426614174000; qcai_guest_csrf=3b1f2f40-7132-4778-8df5-44c1c5cf6bb0",
  );
  const originalFetch = global.fetch;
  let capturedHeaders: Headers | null = null;

  global.fetch = async (_input, init) => {
    capturedHeaders = new Headers(init?.headers);
    return Response.json({ status: "accepted" });
  };

  try {
    await postPublicWebVital({
      metric_id: "vital-1",
      metric_name: "LCP",
      path: "/builder",
      value: 1825.5,
      rating: "good",
    });
  } finally {
    cleanupBrowser();
    global.fetch = originalFetch;
  }

  assert.equal(capturedHeaders?.get("x-qcai-csrf"), "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0");
  assert.equal(capturedHeaders?.get("x-demo-user"), null);
});

test("public support requests also forward guest CSRF headers when present", async () => {
  const cleanupBrowser = withBrowserCookies(
    "qcai_guest_id=guest-123e4567-e89b-12d3-a456-426614174000; qcai_guest_csrf=3b1f2f40-7132-4778-8df5-44c1c5cf6bb0",
  );
  const originalFetch = global.fetch;
  let capturedHeaders: Headers | null = null;

  global.fetch = async (_input, init) => {
    capturedHeaders = new Headers(init?.headers);
    return Response.json({ status: "received", ticket_id: "SUP-0001", response_target: "2 business days" });
  };

  try {
    await submitSupportRequest({
      name: "Audit Reviewer",
      email: "audit@example.test",
      request_type: "product",
      message: "Please verify the public support route.",
    });
  } finally {
    cleanupBrowser();
    global.fetch = originalFetch;
  }

  assert.equal(capturedHeaders?.get("x-qcai-csrf"), "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0");
  assert.equal(capturedHeaders?.get("x-demo-user"), null);
});
