"""Reporting queries."""
from typing import List

from sqlalchemy.orm import Session

from app.schemas import TopBook


def top_books(db: Session, limit: int = 5) -> List[TopBook]:
    """Best-selling books.

    Rules: copies_sold sums quantities over ``paid`` orders only; books with no sales are
    excluded; sorted by copies_sold desc, then title asc; at most ``limit`` rows.
    """
    from sqlalchemy import func, select
    from app.models import Book, Order, OrderItem, OrderStatus

    stmt = (
        select(
            OrderItem.book_id,
            Book.title,
            func.sum(OrderItem.quantity).label("copies_sold"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(Book, OrderItem.book_id == Book.id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(OrderItem.book_id, Book.title)
        .having(func.sum(OrderItem.quantity) > 0)
        .order_by(func.sum(OrderItem.quantity).desc(), Book.title.asc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    return [TopBook(book_id=r.book_id, title=r.title, copies_sold=r.copies_sold) for r in rows]
