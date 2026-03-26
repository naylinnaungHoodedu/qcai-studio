from app.services.store import get_qa_engine
from app.workers.common import LOGGER, run_worker


def startup() -> None:
    engine = get_qa_engine()
    LOGGER.info("RAG worker initialized with retrieval backend %s", engine.settings.openai_chat_model)


if __name__ == "__main__":
    run_worker("rag", on_start=startup, interval_seconds=180)
