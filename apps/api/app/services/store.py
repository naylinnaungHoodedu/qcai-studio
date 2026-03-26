from functools import lru_cache

from app.core.config import get_settings
from app.services.content_assembler import CourseStore
from app.services.qa_engine import QAEngine


@lru_cache
def get_course_store() -> CourseStore:
    return CourseStore(get_settings())


@lru_cache
def get_qa_engine() -> QAEngine:
    return QAEngine(get_course_store(), get_settings())


def rebuild_course_store() -> CourseStore:
    get_course_store.cache_clear()
    get_qa_engine.cache_clear()
    return get_course_store()
