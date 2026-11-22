"use client";

import { useCallback, useState } from "react";

import type { V3ClaimLabel, V3QueueItem, V3ScanResult } from "@/lib/types";
import {
  EHMF_TEXT,
  SYNTHETIC_REVIEWERS,
  TRIGGER_TEXT,
  VERDICT_TEXT,
  adjudicationPayload,
  reviewerHeaders,
} from "@/lib/v3-review";

// The development reviewer console (Phase 6 spec section 11): the queue in the API's order, an item's claim text and its
// shown spans only, and Claim, Adjudicate and Apply for reviewable items. It keeps nothing in browser storage.
const BASE = "/api/backend/v3";

async function call<T>(path: string, reviewer: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: init?.method ?? "GET",
    headers: { "content-type": "application/json", ...reviewerHeaders(reviewer) },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof payload?.detail === "string" ? payload.detail : `The API answered ${response.status}.`);
  }
  return payload as T;
}

type Draft = Record<string, V3ClaimLabel>;

export function V3ReviewConsole() {
  const [reviewer, setReviewer] = useState<string>(SYNTHETIC_REVIEWERS[0]);
  const [items, setItems] = useState<V3QueueItem[]>([]);
  const [selected, setSelected] = useState<V3QueueItem | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [abstention, setAbstention] = useState<"correct" | "missed_answer" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const queue = await call<{ items: V3QueueItem[] }>("/queue?limit=50", reviewer);
      setItems(queue.items);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The queue could not be read.");
    }
  }, [reviewer]);

  async function scan() {
    try {
      const result = await call<V3ScanResult>("/scan", reviewer, { method: "POST" });
      setMessage(`Scanned ${result.records} records; ${result.items_created} items created.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The scan failed.");
    }
  }

  async function open(item: V3QueueItem) {
    const detail = await call<V3QueueItem>(`/items/${item.item_id}`, reviewer);
    setSelected(detail);
    setDraft(
      Object.fromEntries(detail.claims.map((claim) => [claim.claim_id, { claim_id: claim.claim_id, verdict: "SUPPORTED", ehmf_type: null }])),
    );
    setAbstention(detail.decision === "abstain" && detail.subject === "response" ? "correct" : null);
  }

  async function act(action: "claim" | "adjudicate" | "apply") {
    if (!selected) {
      return;
    }
    try {
      const body =
        action === "adjudicate"
          ? adjudicationPayload(Object.values(draft), abstention, crypto.randomUUID())
          : action === "apply"
            ? { client_key: crypto.randomUUID() }
            : undefined;
      await call(`/items/${selected.item_id}/${action}`, reviewer, { method: "POST", body });
      setMessage(`${action} done for ${selected.item_id}.`);
      await open(selected);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${action} failed.`);
    }
  }

  return (
    <section className="mt-6 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">
          Synthetic reviewer{" "}
          <select value={reviewer} onChange={(event) => setReviewer(event.target.value)} className="rounded border px-2 py-1">
            {SYNTHETIC_REVIEWERS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => void scan()} className="rounded border px-3 py-1 text-sm">
          Scan
        </button>
        <button type="button" onClick={() => void refresh()} className="rounded border px-3 py-1 text-sm">
          Refresh
        </button>
      </div>
      {message ? <p className="text-sm" role="status">{message}</p> : null}
      <ol className="space-y-2">
        {items.map((item, rank) => (
          <li key={item.item_id} className="rounded border p-2 text-sm">
            <button type="button" onClick={() => void open(item)} className="text-left">
              #{rank + 1} {item.item_id} · {item.triggers.map((trigger) => TRIGGER_TEXT[trigger] ?? trigger).join(", ") || item.reasons.join(", ")}
              {item.held ? " · held" : ""} · {Math.round(item.age_s / 60)} min · {item.state}
              {item.reviewable ? "" : " · not reviewable"}
            </button>
          </li>
        ))}
      </ol>
      {selected ? (
        <article className="rounded border p-3 text-sm">
          <h2 className="font-semibold">{selected.item_id}</h2>
          <p>
            {selected.subject} item, round {selected.review_round}, {selected.state}
          </p>
          {selected.claims.map((claim) => (
            <div key={claim.claim_id} className="mt-3">
              <p>{claim.text ?? "This claim cites a span that is not shown, so it cannot be reviewed."}</p>
              <ul className="ml-4 list-disc">
                {claim.spans
                  .filter((span) => span.shown)
                  .map((span) => (
                    <li key={span.span_id}>{span.text}</li>
                  ))}
              </ul>
              {selected.reviewable ? (
                <div className="mt-1 flex gap-2">
                  <select
                    value={draft[claim.claim_id]?.verdict ?? "SUPPORTED"}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        [claim.claim_id]: {
                          claim_id: claim.claim_id,
                          verdict: event.target.value as V3ClaimLabel["verdict"],
                          ehmf_type: draft[claim.claim_id]?.ehmf_type ?? "A",
                        },
                      })
                    }
                  >
                    {Object.entries(VERDICT_TEXT).map(([value, text]) => (
                      <option key={value} value={value}>
                        {text}
                      </option>
                    ))}
                  </select>
                  <select
                    value={draft[claim.claim_id]?.ehmf_type ?? "A"}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        [claim.claim_id]: {
                          ...(draft[claim.claim_id] ?? { claim_id: claim.claim_id, verdict: "CONTRADICTED" }),
                          ehmf_type: event.target.value as V3ClaimLabel["ehmf_type"],
                        },
                      })
                    }
                  >
                    {Object.entries(EHMF_TEXT).map(([value, text]) => (
                      <option key={value} value={value}>
                        {text}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
            </div>
          ))}
          {selected.reviewable && selected.subject === "response" && selected.decision === "abstain" ? (
            <select value={abstention ?? "correct"} onChange={(event) => setAbstention(event.target.value as "correct" | "missed_answer")}>
              <option value="correct">The abstention was correct</option>
              <option value="missed_answer">An answer was missed</option>
            </select>
          ) : null}
          {selected.reviewable ? (
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => void act("claim")} className="rounded border px-3 py-1">
                Claim
              </button>
              <button type="button" onClick={() => void act("adjudicate")} className="rounded border px-3 py-1">
                Adjudicate
              </button>
              <button type="button" onClick={() => void act("apply")} className="rounded border px-3 py-1">
                Apply
              </button>
            </div>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}
