"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { chatWithTeachingAssistant, postAnalyticsEvent } from "@/lib/api";
import { AssistantChatMessage, AssistantChatResponse } from "@/lib/types";

type ChatBubble = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  citations?: AssistantChatResponse["citations"];
  isError?: boolean;
};

function buildWelcomeMessage(): ChatBubble {
  return {
    id: "assistant-welcome",
    role: "assistant",
    content:
      "Welcome to QC+AI Studio. Ask about quantum computing, course modules, or a specific concept and I will help from the course materials.",
    createdAt: new Date().toISOString(),
  };
}

function toErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The teaching assistant is unavailable right now.";
}

function buildMessageId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function inferLessonSlug(pathname: string): string | undefined {
  const match = pathname.match(/^\/lessons\/([^/?#]+)/);
  return match?.[1];
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function RobotIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 4v3" />
      <rect x="5" y="7" width="14" height="11" rx="3" />
      <path d="M9 2h6" />
      <path d="M8 12h.01" />
      <path d="M16 12h.01" />
      <path d="M9 16h6" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M22 2 11 13" />
      <path d="m22 2-7 20-4-9-9-4Z" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m12 2 1.9 4.8L19 8.7l-4 3.4 1.2 5.2L12 14.6 7.8 17.3 9 12.1 5 8.7l5.1-1.9Z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m6 6 12 12" />
      <path d="M18 6 6 18" />
    </svg>
  );
}

export function TeachingAssistantChat() {
  const pathname = usePathname() ?? "/";
  const lessonSlug = inferLessonSlug(pathname);
  const [isOpen, setIsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatBubble[]>(() => [buildWelcomeMessage()]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [isOpen, messages, isSending]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handleKeydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [isOpen]);

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) {
      return;
    }

    const userBubble: ChatBubble = {
      id: buildMessageId("user"),
      role: "user",
      content: message,
      createdAt: new Date().toISOString(),
    };
    const history: AssistantChatMessage[] = [...messages, userBubble]
      .slice(-8)
      .map((item) => ({ role: item.role, content: item.content }));

    setDraft("");
    setError(null);
    setMessages((current) => [...current, userBubble]);
    setIsSending(true);

    try {
      const response = await chatWithTeachingAssistant({
        message,
        lesson_slug: lessonSlug,
        page_path: pathname,
        history,
      });

      const assistantBubble: ChatBubble = {
        id: buildMessageId("assistant"),
        role: "assistant",
        content: response.answer,
        createdAt: new Date().toISOString(),
        citations: response.citations,
      };
      setMessages((current) => [...current, assistantBubble]);
      void postAnalyticsEvent("teaching_assistant_message", lessonSlug, {
        page_path: pathname,
        provider: response.provider,
        model: response.model,
        citation_count: response.citations.length,
      }).catch(() => null);
    } catch (nextError) {
      const messageText = toErrorMessage(nextError);
      setError(messageText);
      setMessages((current) => [
        ...current,
        {
          id: buildMessageId("assistant-error"),
          role: "assistant",
          content: messageText,
          createdAt: new Date().toISOString(),
          isError: true,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  function focusComposer() {
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  }

  function openAssistant() {
    setError(null);
    setIsOpen(true);
    focusComposer();
  }

  return (
    <div className="assistant-shell" data-open={isOpen ? "true" : "false"}>
      {isOpen ? (
        <aside
          aria-busy={isSending}
          aria-describedby="assistant-compose-note"
          aria-labelledby="assistant-panel-title"
          aria-modal="false"
          className="assistant-panel"
          id="teaching-assistant-panel"
          role="dialog"
        >
          <header className="assistant-panel-header">
            <div className="assistant-panel-title">
              <div className="assistant-panel-badge" aria-hidden="true">
                <RobotIcon />
              </div>
              <div className="assistant-panel-heading">
                <strong id="assistant-panel-title">Quantum Teaching Assistant</strong>
                <p className="assistant-status-line">
                  <span className="assistant-status-dot" aria-hidden="true" />
                  Online &amp; ready to help
                </p>
              </div>
            </div>
            <button
              aria-label="Close teaching assistant"
              className="assistant-close-button"
              onClick={() => setIsOpen(false)}
              type="button"
            >
              <CloseIcon />
            </button>
          </header>

          <div className="assistant-transcript-surface">
            <div
              aria-busy={isSending}
              aria-live="polite"
              aria-relevant="additions text"
              className="assistant-transcript"
              ref={transcriptRef}
              role="log"
            >
              {messages.map((message) => (
                <article
                  className={`assistant-bubble assistant-bubble--${message.role}${message.isError ? " is-error" : ""}`}
                  key={message.id}
                >
                  <p>{message.content}</p>
                  {message.citations?.length ? (
                    <div className="assistant-citation-list">
                      {message.citations.map((citation, index) => (
                        <div className="assistant-citation" key={`${message.id}-${citation.chunk_id}`}>
                          <strong>
                            [{index + 1}] {citation.section_title}
                          </strong>
                          <span>
                            {citation.source_title}
                            {citation.timestamp_label ? ` | ${citation.timestamp_label}` : ""}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <time className="assistant-bubble-time" dateTime={message.createdAt}>
                    {formatTimestamp(message.createdAt)}
                  </time>
                </article>
              ))}
              {isSending ? (
                <article className="assistant-bubble assistant-bubble--assistant">
                  <p>Thinking through the grounded course material...</p>
                </article>
              ) : null}
            </div>
          </div>

          <form className="assistant-compose" onSubmit={submitMessage}>
            <label className="sr-only" htmlFor="assistant-message">
              Ask the teaching assistant
            </label>
            <div className="assistant-compose-input">
              <textarea
                id="assistant-message"
                maxLength={2000}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask about quantum computing..."
                ref={textareaRef}
                rows={1}
                value={draft}
              />
              <button
                aria-label={isSending ? "Sending message" : "Send message"}
                className="primary-button assistant-send-button"
                disabled={isSending || !draft.trim()}
                type="submit"
              >
                <SendIcon />
                <span className="sr-only">{isSending ? "Sending message" : "Send message"}</span>
              </button>
            </div>
            <p className="assistant-compose-note muted" id="assistant-compose-note">
              Ask me about qubits, gates, algorithms, or our course materials.
            </p>
            {error ? <p className="assistant-compose-error">{error}</p> : null}
          </form>
        </aside>
      ) : null}

      {!isOpen ? (
        <button
          aria-controls="teaching-assistant-panel"
          aria-expanded={isOpen}
          aria-haspopup="dialog"
          aria-label="Open teaching assistant"
          className="assistant-launcher"
          onClick={openAssistant}
          type="button"
        >
          <span className="assistant-launcher-icon" aria-hidden="true">
            <RobotIcon />
            <span className="assistant-launcher-star">
              <StarIcon />
            </span>
          </span>
          <span className="sr-only">Teaching assistant</span>
        </button>
      ) : null}
    </div>
  );
}
