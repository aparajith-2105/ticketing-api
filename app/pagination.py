import math
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class PageParams:
    def __init__(self, page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100)):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


def paginate(db: Session, stmt, params: PageParams, schema):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(params.page_size).offset(params.offset)).all()
    return Page[schema](items=[schema.model_validate(r) for r in rows], total=total,
                        page=params.page, page_size=params.page_size,
                        pages=math.ceil(total / params.page_size))