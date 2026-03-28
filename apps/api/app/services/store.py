from functools import lru_cache

from app.core.config import get_settings
from app.services.content_assembler import CourseStore
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine


@lru_cache
def get_course_store() -> CourseStore:
    return CourseStore(get_settings())


@lru_cache
def get_retrieval_engine() -> RetrievalEngine:
    return RetrievalEngine(get_course_store(), get_settings())


@lru_cache
def get_qa_engine() -> QAEngine:
    return QAEngine(get_retrieval_engine(), get_settings())


def rebuild_course_store() -> CourseStore:
    get_course_store.cache_clear()
    get_retrieval_engine.cache_clear()
    get_qa_engine.cache_clear()
    return get_course_store()
