from __future__ import annotations

import logging
import os
from functools import cached_property
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.schemas import (
    ASSISTANT_HISTORY_MAX_MESSAGES,
    ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH,
    AssistantChatMessage,
    AssistantChatResponse,
    Citation,
)
from app.services.retrieval_engine import RetrievalEngine
from app.services.text_utils import sanitize_user_text, truncate_display_excerpt

try:
    import google.auth
    from google.auth.transport.requests import Request as GoogleAuthRequest
except Exception as exc:  # pragma: no cover - depends on deployment packaging.
    google = None
    GoogleAuthRequest = None
    GOOGLE_AUTH_IMPORT_ERROR = exc
else:
    GOOGLE_AUTH_IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)
VERTEX_AI_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class TeachingAssistantService:
    def __init__(self, retrieval_engine: RetrievalEngine, settings: Settings):
        self.retrieval_engine = retrieval_engine
        self.settings = settings

    def chat(
        self,
        message: str,
        *,
        lesson_slug: str | None = None,
        page_path: str | None = None,
        history: list[AssistantChatMessage] | None = None,
        top_k: int = 4,
    ) -> AssistantChatResponse:
        clean_message = sanitize_user_text(message)
        clean_page_path = sanitize_user_text(page_path or "", preserve_newlines=False) or None
        clean_history = self._sanitize_history(history or [])

        retrieval = self.retrieval_engine.search(clean_message, lesson_slug=lesson_slug, top_k=top_k)
        citations = [
            Citation(
                chunk_id=hit.chunk_id,
                source_title=hit.source_title,
                source_kind=hit.source_kind,
                section_title=hit.title,
                excerpt=truncate_display_excerpt(hit.excerpt, 320),
                timestamp_label=hit.timestamp_label,
            )
            for hit in retrieval.results
        ]

        if not citations:
            return AssistantChatResponse(
                answer=(
                    "I could not ground an answer in the indexed QC+AI course sources yet. "
                    "Try naming a module, lesson, workflow, or specific topic such as routing, kernels, "
                    "QUBO optimization, quantum finance programming, or hardware-constrained model validation."
                ),
                citations=[],
                retrieval_mode=f"{retrieval.mode}-no-match",
                provider="local-grounded-fallback",
                model="qcai-course-corpus",
                grounded=False,
            )

        if self.vertex_enabled:
            try:
                answer = self._ask_vertex(
                    message=clean_message,
                    lesson_slug=lesson_slug,
                    page_path=clean_page_path,
                    history=clean_history,
                    citations=citations,
                )
                return AssistantChatResponse(
                    answer=answer,
                    citations=citations,
                    retrieval_mode=f"vertex-rag-{retrieval.mode}",
                    provider=self._vertex_provider_label,
                    model=self.settings.vertex_ai_chat_model,
                    grounded=True,
                )
            except Exception as exc:
                LOGGER.warning("Vertex assistant failed; using grounded fallback: %s", exc)

        return AssistantChatResponse(
            answer=self._fallback_answer(clean_message, citations, page_path=clean_page_path),
            citations=citations,
            retrieval_mode=f"{retrieval.mode}-grounded-fallback",
            provider="local-grounded-fallback",
            model="qcai-course-corpus",
            grounded=True,
        )

    @property
    def vertex_enabled(self) -> bool:
        return bool(self.vertex_api_key or self.vertex_project_id)

    @property
    def vertex_api_key(self) -> str | None:
        explicit = (self.settings.vertex_ai_api_key or "").strip()
        if explicit:
            return explicit
        env_value = (os.getenv("VERTEX_AI_API_KEY") or "").strip()
        return env_value or None

    @cached_property
    def _google_auth_bundle(self) -> tuple[object, str | None]:
        if not google:
            raise RuntimeError(f"google-auth is unavailable: {GOOGLE_AUTH_IMPORT_ERROR}")
        credentials, discovered_project = google.auth.default(scopes=[VERTEX_AI_SCOPE])
        return credentials, discovered_project

    @property
    def vertex_project_id(self) -> str | None:
        explicit = (self.settings.vertex_ai_project_id or "").strip()
        if explicit:
            return explicit
        env_value = (os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT") or "").strip()
        if env_value:
            return env_value
        try:
            _, discovered_project = self._google_auth_bundle
        except Exception:
            return None
        return (discovered_project or "").strip() or None

    def _sanitize_history(self, history: list[AssistantChatMessage]) -> list[AssistantChatMessage]:
        cleaned: list[AssistantChatMessage] = []
        for item in history[-ASSISTANT_HISTORY_MAX_MESSAGES:]:
            content = sanitize_user_text(item.content)[:ASSISTANT_HISTORY_MESSAGE_MAX_LENGTH]
            if not content:
                continue
            cleaned.append(item.model_copy(update={"content": content}))
        return cleaned[-ASSISTANT_HISTORY_MAX_MESSAGES:]

    def _ask_vertex(
        self,
        *,
        message: str,
        lesson_slug: str | None,
        page_path: str | None,
        history: list[AssistantChatMessage],
        citations: list[Citation],
    ) -> str:
        prompt_context = self._format_context(citations)
        page_context = self._format_page_context(page_path=page_path, lesson_slug=lesson_slug)
        contents = [
            {
                "role": "user" if item.role == "user" else "model",
                "parts": [{"text": item.content}],
            }
            for item in history
        ]
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"Current page context: {page_context}\n\n"
                            f"Question: {message}\n\n"
                            f"Grounded course context:\n{prompt_context}"
                        )
                    }
                ],
            }
        )

        payload = {
            "systemInstruction": {
                "role": "system",
                "parts": [
                    {
                        "text": (
                            "You are the QC+AI Studio teaching assistant. "
                            "Answer from the supplied course context only. "
                            "Be precise, concise, and instructional. "
                            "If the evidence is partial, say so explicitly. "
                            "Cite supporting context with bracket numbers like [1] or [2]. "
                            "Do not invent labs, lessons, or source material that are not present in the context."
                        )
                    }
                ],
            },
            "contents": contents,
            "generationConfig": {
                "temperature": 0.25,
                "topP": 0.9,
                "maxOutputTokens": 1024,
            },
        }

        response = self._vertex_client.post(
            self._vertex_endpoint,
            headers=self._vertex_headers(),
            json=payload,
        )
        response.raise_for_status()
        answer = self._extract_text(response.json())
        if not answer:
            raise RuntimeError("Vertex AI returned an empty response.")
        return answer

    @cached_property
    def _vertex_client(self) -> httpx.Client:
        return httpx.Client(timeout=35.0)

    @property
    def _vertex_endpoint(self) -> str:
        model = self.settings.vertex_ai_chat_model.strip()
        if self.vertex_api_key:
            query = urlencode({"key": self.vertex_api_key})
            return f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent?{query}"

        project_id = self.vertex_project_id
        if not project_id:
            raise RuntimeError("Vertex AI project ID is unavailable.")
        location = self.settings.vertex_ai_location.strip() or "global"
        return (
            "https://aiplatform.googleapis.com/v1/"
            f"projects/{project_id}/locations/{location}/publishers/google/models/{model}:generateContent"
        )

    @property
    def _vertex_provider_label(self) -> str:
        return "vertex-ai-api-key" if self.vertex_api_key else "vertex-ai-service-account"

    def _access_token(self) -> str:
        credentials, _ = self._google_auth_bundle
        if not getattr(credentials, "valid", False):
            if not GoogleAuthRequest:
                raise RuntimeError("google-auth transport helpers are unavailable.")
            credentials.refresh(GoogleAuthRequest())
        token = getattr(credentials, "token", None)
        if not token:
            raise RuntimeError("Google application credentials did not provide an access token.")
        return token

    def _vertex_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.vertex_api_key:
            return headers
        headers["Authorization"] = f"Bearer {self._access_token()}"
        return headers

    def _format_context(self, citations: list[Citation]) -> str:
        return "\n\n".join(
            (
                f"[{index}] Source: {citation.source_title} | Section: {citation.section_title} "
                f"| Type: {citation.source_kind} | Time: {citation.timestamp_label or 'n/a'}\n"
                f"{citation.excerpt}"
            )
            for index, citation in enumerate(citations, start=1)
        )

    def _format_page_context(self, *, page_path: str | None, lesson_slug: str | None) -> str:
        parts: list[str] = []
        if page_path:
            parts.append(f"path={page_path}")
        if lesson_slug:
            parts.append(f"lesson_slug={lesson_slug}")
        if not parts:
            return "public site context"
        return ", ".join(parts)

    def _extract_text(self, payload: dict) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return ""

        fragments: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    fragments.append(part["text"])
        return "\n".join(fragment.strip() for fragment in fragments if fragment.strip()).strip()

    def _fallback_answer(
        self,
        question: str,
        citations: list[Citation],
        *,
        page_path: str | None = None,
    ) -> str:
        lead = citations[0]
        supporting = citations[1:3]
        lowered = question.lower()
        parts = [f"The strongest grounded evidence comes from {lead.source_title} in '{lead.section_title}'."]

        if page_path:
            parts.append(f"I answered this in the context of {page_path}.")

        if "study" in lowered or "learn" in lowered:
            parts.extend(
                [
                    "A sound way to study this material is to move from the module summary to the named lesson, "
                    "then focus on the bottleneck, workflow, or validation rule the sources keep repeating.",
                    lead.excerpt,
                ]
            )
        else:
            parts.append(lead.excerpt)

        if supporting:
            parts.append(
                "Supporting context also appears in "
                + "; ".join(
                    f"{item.source_title} ({item.section_title}{', ' + item.timestamp_label if item.timestamp_label else ''})"
                    for item in supporting
                )
                + "."
            )

        if "how" in lowered:
            parts.append(
                "Operationally, the course materials keep returning to a hybrid flow: classical framing, "
                "a smaller constrained quantum subroutine, then classical interpretation or control."
            )
        elif "why" in lowered:
            parts.append(
                "The repeated reason across the corpus is hardware realism: noise, routing cost, qubit limits, "
                "and validation discipline shape what is worth doing."
            )
        else:
            parts.append(
                "The safest interpretation is to read the answer through hardware-constrained hybrid systems rather than abstract quantum advantage alone."
            )

        return " ".join(parts)
