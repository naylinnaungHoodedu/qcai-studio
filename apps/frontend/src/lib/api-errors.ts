type ValidationIssue = {
  loc?: Array<string | number>;
  msg?: string;
};

function formatValidationIssue(issue: ValidationIssue): string | null {
  const location = Array.isArray(issue.loc)
    ? issue.loc
        .filter((segment) => segment !== "body")
        .map((segment) => String(segment))
        .join(".")
    : "";
  const message = typeof issue.msg === "string" ? issue.msg.trim() : "";

  if (location.includes("history")) {
    return "The assistant context was too long. Please send the question again.";
  }
  if (!message) {
    return null;
  }
  if (!location) {
    return message;
  }
  return `${location}: ${message}`;
}

function formatRetryAfter(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const seconds = Number.parseInt(value, 10);
  if (Number.isFinite(seconds) && seconds > 0) {
    return `Too many requests right now. Wait about ${seconds} seconds and try again.`;
  }
  return "Too many requests right now. Please wait and try again.";
}

export function describeApiError(
  status: number,
  headers: Headers,
  payload: { detail?: unknown; error?: unknown },
): string | null {
  if (status === 429) {
    return formatRetryAfter(headers.get("retry-after"));
  }

  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }

  if (Array.isArray(payload.detail)) {
    const firstMessage = payload.detail
      .map((issue) => formatValidationIssue(issue as ValidationIssue))
      .find((message): message is string => Boolean(message));
    if (firstMessage) {
      return firstMessage;
    }
  }

  if (typeof payload.error === "string" && payload.error.trim()) {
    return payload.error;
  }

  return null;
}
