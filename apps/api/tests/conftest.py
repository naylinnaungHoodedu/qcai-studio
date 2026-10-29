import os


# Tests write and delete rows, so they never use an ambient DATABASE_URL: only in-memory SQLite, or the
# disposable database named by TEST_DATABASE_URL (the PostgreSQL CI job, task 1.10).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")

# Keep direct service tests on the same complete in-memory schema as API tests.
from app.main import _initialize_database

_initialize_database()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "release_artifacts: needs packaged dist/release bundles; runs only in the release-artifacts CI job",
    )
