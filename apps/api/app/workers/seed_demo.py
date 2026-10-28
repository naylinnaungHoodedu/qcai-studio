from app.core.db import Base, SessionLocal, engine
from app.services.demo_seed import seed_demo_data
from app.workers.common import LOGGER


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        report = seed_demo_data(session)
    LOGGER.info(
        "seed_demo completed: created=%s updated=%s unchanged=%s",
        report.total_created,
        report.total_updated,
        report.total_unchanged,
    )


if __name__ == "__main__":
    main()
