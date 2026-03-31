"use client";

import { FormEvent, useState, useTransition } from "react";

import { submitSupportRequest } from "@/lib/api";
import { SUPPORT_REQUEST_TYPES } from "@/lib/operations-governance";
import { SupportRequestReceipt } from "@/lib/types";

type SupportFormState = {
  name: string;
  email: string;
  organization: string;
  requestType: string;
  pageUrl: string;
  message: string;
  website: string;
};

const INITIAL_FORM: SupportFormState = {
  name: "",
  email: "",
  organization: "",
  requestType: SUPPORT_REQUEST_TYPES[0].value,
  pageUrl: "",
  message: "",
  website: "",
};

export function SupportIntakeForm() {
  const [form, setForm] = useState(() => ({
    ...INITIAL_FORM,
    pageUrl: typeof window !== "undefined" ? window.location.href : "",
  }));
  const [result, setResult] = useState<SupportRequestReceipt | null>(null);
  const [error, setError] = useState("");
  const [isPending, startTransition] = useTransition();

  function updateField<K extends keyof SupportFormState>(key: K, value: SupportFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setResult(null);
    startTransition(() => {
      void submitSupportRequest({
        name: form.name,
        email: form.email,
        organization: form.organization || null,
        request_type: form.requestType,
        page_url: form.pageUrl || null,
        message: form.message,
        website: form.website || null,
      })
        .then((receipt) => {
          setResult(receipt);
          setForm((current) => ({
            ...INITIAL_FORM,
            pageUrl: current.pageUrl,
          }));
        })
        .catch((submissionError: unknown) => {
          setError(submissionError instanceof Error ? submissionError.message : "Could not send the support request.");
        });
    });
  }

  return (
    <form className="account-form support-intake-form" onSubmit={handleSubmit}>
      <div className="analytics-form-grid">
        <label>
          <span>Name</span>
          <input
            autoComplete="name"
            name="name"
            onChange={(event) => updateField("name", event.target.value)}
            required
            type="text"
            value={form.name}
          />
        </label>
        <label>
          <span>Email</span>
          <input
            autoComplete="email"
            name="email"
            onChange={(event) => updateField("email", event.target.value)}
            required
            type="email"
            value={form.email}
          />
        </label>
        <label>
          <span>Request type</span>
          <select
            name="request_type"
            onChange={(event) => updateField("requestType", event.target.value)}
            value={form.requestType}
          >
            {SUPPORT_REQUEST_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Organization</span>
          <input
            autoComplete="organization"
            name="organization"
            onChange={(event) => updateField("organization", event.target.value)}
            type="text"
            value={form.organization}
          />
        </label>
      </div>

      <label>
        <span>Message</span>
        <textarea
          className="note-input support-message-input"
          name="message"
          onChange={(event) => updateField("message", event.target.value)}
          required
          rows={7}
          value={form.message}
        />
      </label>

      <label className="support-honeypot" tabIndex={-1}>
        <span>Website</span>
        <input
          autoComplete="off"
          name="website"
          onChange={(event) => updateField("website", event.target.value)}
          tabIndex={-1}
          type="text"
          value={form.website}
        />
      </label>

      <input name="page_url" readOnly type="hidden" value={form.pageUrl} />

      <div className="button-row">
        <button className="primary-button" disabled={isPending} type="submit">
          {isPending ? "Sending request..." : "Send support request"}
        </button>
      </div>

      <div aria-live="polite" className="stack" role="status">
        {result ? (
          <div className="success-banner">
            <strong>{result.ticket_id}</strong>
            <p>
              Request received. Type: {result.request_type}. Response target: {result.response_target}
            </p>
          </div>
        ) : null}
        {error ? (
          <div className="error-banner">
            <strong>Submission failed</strong>
            <p>{error}</p>
          </div>
        ) : null}
      </div>
    </form>
  );
}
