from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.schemas import SearchResult
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.services.store import get_retrieval_engine

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=list[SearchResult])
@limiter.limit(lambda: get_settings().search_rate_limit)
def search_content(
    request: Request,
    response: Response,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    lesson_slug: str | None = None,
    top_k: Annotated[int, Query(ge=1, le=20)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    retrieval = get_retrieval_engine().search(query=query.strip(), lesson_slug=lesson_slug, top_k=top_k + offset)
    response.headers["X-Retrieval-Mode"] = retrieval.mode
    return retrieval.results[offset : offset + top_k]
