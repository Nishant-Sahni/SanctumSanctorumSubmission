"""Order operations: placing, paying and cancelling purchases."""
from datetime import datetime
from typing import Dict, List

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Book, Member, MemberTier, Order, OrderItem, OrderStatus
from app.schemas import OrderCreate, OrderItemIn
from app.services.books import get_book, release_stock, reserve_stock
from app.services.members import ensure_can_access_restricted, get_member

# Percentage discount granted by each membership tier.
TIER_DISCOUNT_PERCENT: Dict[str, int] = {
    MemberTier.APPRENTICE.value: 0,
    MemberTier.ADEPT.value: 5,
    MemberTier.MASTER.value: 10,
    MemberTier.SUPREME.value: 15,
}

# Extra discount when the total quantity across all items reaches the threshold.
BULK_QUANTITY_THRESHOLD = 10
BULK_DISCOUNT_PERCENT = 5


def calculate_discount_percent(member: Member, total_quantity: int) -> int:
    """Tier discount, plus the bulk discount when total quantity >= threshold."""
    pct = TIER_DISCOUNT_PERCENT[member.tier]
    if total_quantity >= BULK_QUANTITY_THRESHOLD:
        pct += BULK_DISCOUNT_PERCENT
    return pct




def _reserve_stock_for_items(db: Session, items: List[OrderItemIn], books: Dict[int, Book]) -> None:
    """Reserve stock for every item, or for none of them (409 on the first shortfall)."""
    for item in items:
        if not reserve_stock(db, item.book_id, item.quantity):
            # Build the message first: rollback expires every loaded object.
            detail = f"Insufficient stock for '{books[item.book_id].title}'"
            # Undo the reservations already made for earlier items in this order.
            db.rollback()
            raise HTTPException(status_code=409, detail=detail)


def create_order(db: Session, data: OrderCreate, now: datetime) -> Order:
    """Place a pending order and reserve stock.

    Checks, in order (422 for empty items / bad quantity / duplicate books is done by the schema):
    1. 404 member not found; 404 any book not found
    2. 403 any book restricted and member tier below master
    3. 409 any book has insufficient stock (all-or-nothing: nothing is changed)
    Stock is reserved with conditional UPDATEs, so concurrent orders cannot oversell.
    Prices are snapshotted at order time.
    Pricing: discount_cents = subtotal * percent // 100; total = subtotal - discount.
    """
    member = get_member(db, data.member_id)
    books: Dict[int, Book] = {}
    for item in data.items:
        books[item.book_id] = get_book(db, item.book_id)

    for item in data.items:
        if books[item.book_id].restricted:
            ensure_can_access_restricted(member)
            break

    _reserve_stock_for_items(db, data.items, books)

    order_items = [
        OrderItem(
            book_id=item.book_id,
            quantity=item.quantity,
            unit_price_cents=books[item.book_id].price_cents,
        )
        for item in data.items
    ]

    total_qty = sum(item.quantity for item in data.items)
    subtotal = sum(oi.unit_price_cents * oi.quantity for oi in order_items)
    discount_percent = calculate_discount_percent(member, total_qty)
    discount_cents = subtotal * discount_percent // 100
    total_cents = subtotal - discount_cents

    order = Order(
        member_id=data.member_id,
        status=OrderStatus.PENDING.value,
        subtotal_cents=subtotal,
        discount_percent=discount_percent,
        discount_cents=discount_cents,
        total_cents=total_cents,
        created_at=now,
        items=order_items,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_order(db: Session, order_id: int) -> Order:
    """Return an order by id, or raise 404."""
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _transition_from_pending(db: Session, order: Order, new_status: OrderStatus, action: str) -> None:
    """Move a pending order to `new_status`, or raise 409 if it is no longer pending.

    The status check lives in the UPDATE's WHERE clause, so two concurrent
    requests cannot both move the same order out of `pending`.
    """
    result = db.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == OrderStatus.PENDING.value)
        .values(status=new_status.value)
    )
    if result.rowcount == 0:
        # Reload so the message shows the status that was actually committed.
        db.refresh(order)
        raise HTTPException(status_code=409, detail=f"Cannot {action} an order that is {order.status}")


def pay_order(db: Session, order_id: int) -> Order:
    """Mark a pending order as paid. 404 if missing; 409 if not pending.

    Stock is unchanged: it was reserved when the order was created.
    """
    order = get_order(db, order_id)
    _transition_from_pending(db, order, OrderStatus.PAID, "pay")
    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order_id: int) -> Order:
    """Cancel a pending order and restore the reserved stock. 404 if missing; 409 if not pending."""
    order = get_order(db, order_id)
    _transition_from_pending(db, order, OrderStatus.CANCELLED, "cancel")
    for item in order.items:
        release_stock(db, item.book_id, item.quantity)
    db.commit()
    db.refresh(order)
    return order