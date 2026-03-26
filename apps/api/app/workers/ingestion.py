from app.services.store import rebuild_course_store
from app.workers.common import LOGGER, run_worker


def startup() -> None:
    store = rebuild_course_store()
    LOGGER.info(
        "Ingestion worker indexed %s modules, %s lessons, and %s chunks",
        len(store.modules),
        len(store.lessons),
        len(store.chunks),
    )


if __name__ == "__main__":
    run_worker("ingestion", on_start=startup, interval_seconds=300)
