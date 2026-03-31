import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


SOURCE_DOCUMENT_NAMES = [
    "Quantum Computing AI Research Synthesis 2026.docx",
    "Analyzing Quantum Computing and AI Paper 2025.docx",
    "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
]

SOURCE_VIDEO_NAMES = [
    "Quantum Computing and Artificial Intelligence 2025.mp4",
    "Quantum Computing and Artificial Intelligence 2026.mp4",
    "Industry Use Cases.mp4",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
]
SQLITE_URL_PREFIX = "sqlite:///"
API_ROOT = Path(__file__).resolve().parents[2]


def normalize_sqlite_database_url(database_url: str) -> str:
    if not database_url.startswith(SQLITE_URL_PREFIX):
        return database_url

    sqlite_path = database_url[len(SQLITE_URL_PREFIX) :]
    if sqlite_path in {"", ":memory:"}:
        return database_url
    if sqlite_path.startswith("/") or (len(sqlite_path) >= 2 and sqlite_path[1] == ":"):
        return database_url

    normalized_path = (API_ROOT / sqlite_path).resolve()
    return f"{SQLITE_URL_PREFIX}{normalized_path.as_posix()}"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "QC+AI Learning API"
    environment: str = "development"
    site_url: str | None = None
    database_url: str = "sqlite:///./qcai_dev.db"
    enable_demo_auth: bool | None = None
    cloud_sql_connection_name: str | None = None
    cloud_sql_ip_type: str = "PUBLIC"
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    vertex_ai_api_key: str | None = None
    vertex_ai_project_id: str | None = None
    vertex_ai_location: str = "global"
    vertex_ai_chat_model: str = "gemini-3.1-flash-lite-preview"
    auth0_domain: str | None = None
    auth0_audience: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index: str | None = None
    pinecone_namespace: str = "qcai-course"
    pinecone_upsert_batch_size: int = 32
    auth_register_rate_limit: str = "5/minute"
    auth_login_rate_limit: str = "10/minute"
    qa_ask_rate_limit: str = "5/minute"
    assistant_chat_rate_limit: str = "8/minute"
    search_rate_limit: str = "10/minute"
    support_request_rate_limit: str = "5/hour"
    public_web_vitals_rate_limit: str = "120/minute"
    api_base_url: str | None = None
    source_assets_root: str | None = None
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return ["http://localhost:3000"]
            if raw_value.startswith("["):
                try:
                    parsed = json.loads(raw_value)
                except ValueError:
                    parsed = None
                if isinstance(parsed, list):
                    return [item for item in parsed if isinstance(item, str) and item.strip()]
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_allowed_origins(self) -> "Settings":
        if self.enable_demo_auth is None:
            self.enable_demo_auth = self.environment.lower() == "development"
        if self.environment.lower() != "development" and any(origin.strip() == "*" for origin in self.allowed_origins):
            raise ValueError("Wildcard ALLOWED_ORIGINS is not permitted outside development.")
        self.database_url = normalize_sqlite_database_url(self.database_url)
        return self

    @property
    def project_root(self) -> Path:
        if self.source_assets_root:
            return Path(self.source_assets_root).resolve()

        config_path = Path(__file__).resolve()
        candidates = [parent for parent in config_path.parents]
        candidates.append(Path("/app/source-assets"))

        for candidate in candidates:
            if all((candidate / name).exists() for name in SOURCE_DOCUMENT_NAMES[:2]):
                return candidate

        for candidate in candidates:
            if all((candidate / name).exists() for name in SOURCE_VIDEO_NAMES):
                return candidate

        return config_path.parents[min(3, len(config_path.parents) - 1)]

    @property
    def source_documents(self) -> list[Path]:
        root = self.project_root
        return [root / name for name in SOURCE_DOCUMENT_NAMES if (root / name).exists()]

    @property
    def source_videos(self) -> list[Path]:
        root = self.project_root
        return [root / name for name in SOURCE_VIDEO_NAMES if (root / name).exists()]

    @property
    def transcripts_dir(self) -> Path:
        return self.project_root / "transcripts"

    @property
    def source_assets_dir(self) -> Path:
        return self.project_root


@lru_cache
def get_settings() -> Settings:
    return Settings()
