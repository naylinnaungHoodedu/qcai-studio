import logging
import signal
import time
from collections.abc import Callable

from app.core.config import get_settings
from app.core.db import Base, engine
from app.core.log_redaction import install_log_redaction

LOGGER = logging.getLogger("qcai.worker")
_settings = get_settings()
install_log_redaction([_settings.vertex_ai_api_key, _settings.openai_api_key, _settings.pinecone_api_key])
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_running = True


def _handle_shutdown(signum, _frame):
    global _running
    LOGGER.info("Received shutdown signal %s", signum)
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


def run_worker(name: str, on_start: Callable[[], None] | None = None, interval_seconds: int = 60) -> None:
    LOGGER.info("%s worker starting", name)
    Base.metadata.create_all(bind=engine)
    if on_start:
        on_start()
    while _running:
        LOGGER.info("%s worker heartbeat", name)
        time.sleep(interval_seconds)
    LOGGER.info("%s worker stopping", name)
