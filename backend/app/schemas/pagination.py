from fastapi import Query
from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class PaginationParams:
    """Shared `?page=&page_size=` query params, reusable by any paginated route."""

    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def limit(self) -> int:
        return self.page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def to_page[T](self, items: list[T], total: int) -> Page[T]:
        return Page(items=items, total=total, page=self.page, page_size=self.page_size)
