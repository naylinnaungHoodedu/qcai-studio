from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas import SearchResult
from app.services.store import get_course_store

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
def search_content(
    query: Annotated[str, Query(min_length=1, max_length=500)],
    lesson_slug: str | None = None,
    top_k: Annotated[int, Query(ge=1, le=20)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    results = get_course_store().search(query=query.strip(), lesson_slug=lesson_slug, top_k=top_k + offset)
    return results[offset : offset + top_k]
