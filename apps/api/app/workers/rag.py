from app.services.store import get_retrieval_engine
from app.workers.common import LOGGER, run_worker


def startup() -> None:
    engine = get_retrieval_engine()
    if engine.sync_semantic_index(refresh=True):
        LOGGER.info("RAG worker refreshed Pinecone semantic index '%s'.", engine.settings.pinecone_index)
    else:
        LOGGER.info("RAG worker initialized with lexical retrieval fallback only.")


if __name__ == "__main__":
    run_worker("rag", on_start=startup, interval_seconds=180)
