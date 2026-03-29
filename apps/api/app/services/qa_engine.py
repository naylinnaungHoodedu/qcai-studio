from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.schemas import Citation, QAResponse
from app.services.retrieval_engine import RetrievalEngine
from app.services.text_utils import truncate_display_excerpt


class QAEngine:
    def __init__(self, retrieval_engine: RetrievalEngine, settings: Settings):
        self.retrieval_engine = retrieval_engine
        self.settings = settings

    def ask(self, question: str, lesson_slug: str | None = None, top_k: int = 4) -> QAResponse:
        retrieval = self.retrieval_engine.search(question, lesson_slug=lesson_slug, top_k=top_k)
        hits = retrieval.results
        citations = [
            Citation(
                chunk_id=hit.chunk_id,
                source_title=hit.source_title,
                source_kind=hit.source_kind,
                section_title=hit.title,
                excerpt=truncate_display_excerpt(hit.excerpt, 320),
                timestamp_label=hit.timestamp_label,
            )
            for hit in hits
        ]
        if not hits:
            return QAResponse(
                answer="I could not ground an answer in the indexed course sources. Try a more specific question about routing, QUBO optimization, quantum kernels, thermodynamic quantum agents, or another named topic from the course.",
                citations=[],
                retrieval_mode=f"{retrieval.mode}-no-match",
            )

        if self.settings.openai_api_key:
            answer = self._ask_with_openai(question, citations)
            mode = f"openai-rag-{retrieval.mode}"
        else:
            answer = self._fallback_answer(question, citations)
            mode = "semantic-grounded-fallback" if retrieval.mode == "hybrid-pinecone" else "local-grounded-fallback"
        return QAResponse(answer=answer, citations=citations, retrieval_mode=mode)

    def _ask_with_openai(self, question: str, citations: list[Citation]) -> str:
        llm = ChatOpenAI(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_chat_model,
            temperature=0.1,
        )
        context = "\n\n".join(
            f"[{idx + 1}] Source: {citation.source_title} | Section: {citation.section_title} | Time: {citation.timestamp_label or 'n/a'}\n{citation.excerpt}"
            for idx, citation in enumerate(citations)
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a rigorous teaching assistant for a graduate QC+AI course. Answer only from the supplied context. If the evidence is incomplete, say so explicitly. Cite supporting items using bracket numbers like [1] or [2].",
                ),
                ("human", "Question: {question}\n\nContext:\n{context}"),
            ]
        )
        response = llm.invoke(prompt.format_messages(question=question, context=context))
        return response.content if isinstance(response.content, str) else str(response.content)

    def _fallback_answer(self, question: str, citations: list[Citation]) -> str:
        lead = citations[0]
        supporting = citations[1:3]
        lowered = question.lower()
        parts = [f"The strongest retrieved evidence comes from {lead.source_title} in the section '{lead.section_title}'."]

        if "qai" in lowered and "ai4qc" in lowered:
            parts.extend(
                [
                    "The course corpus treats them as two related but different directions.",
                    "QAI uses quantum states or circuits to strengthen an AI model's representation, kernel, or decision stage.",
                    "AI4QC uses classical AI to make quantum hardware and quantum workflows more usable through routing, optimization, calibration, or control.",
                ]
            )
        else:
            parts.append(lead.excerpt)

        if supporting:
            support_line = "Supporting context also appears in "
            support_line += "; ".join(
                f"{item.source_title} ({item.section_title}{', ' + item.timestamp_label if item.timestamp_label else ''})"
                for item in supporting
            )
            support_line += "."
            parts.append(support_line)

        if "why" in lowered:
            parts.append("The common thread is that the course materials repeatedly tie algorithmic claims back to hardware bottlenecks, hybrid orchestration, and application-specific constraints.")
        elif "how" in lowered:
            parts.append("Operationally, the sources describe a workflow in which classical preprocessing or control shapes a smaller quantum subroutine, then classical post-processing interprets the result.")
        elif "qai" not in lowered or "ai4qc" not in lowered:
            parts.append("A careful reading of the course corpus suggests interpreting the answer through a hybrid systems lens rather than through abstract quantum advantage alone.")
        return " ".join(parts)
