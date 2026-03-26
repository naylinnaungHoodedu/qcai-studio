from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.db_models import AnalyticsEvent, QAInteraction
from app.workers.common import LOGGER, run_worker


def startup() -> None:
    with SessionLocal() as session:
        event_count = session.scalar(select(func.count()).select_from(AnalyticsEvent)) or 0
        qa_count = session.scalar(select(func.count()).select_from(QAInteraction)) or 0
    LOGGER.info("Analytics worker sees %s analytics events and %s QA interactions", event_count, qa_count)


if __name__ == "__main__":
    run_worker("analytics", on_start=startup, interval_seconds=240)
