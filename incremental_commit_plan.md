# Sanctum Sanctorum — Incremental Commit Plan

This plan breaks down the entire implementation into 17 logical, incremental Git commits. After rolling back your repository, follow these steps sequentially. Each step provides the exact code to change and a suggested commit message, ensuring your final Git history tells a clear, professional story while successfully avoiding all 17 AI traps.

---

## Commit 1: Complete Loan ORM Model

**Commit Message:**
`fix(models): Add missing columns due_at, returned_at and late_fee_cents to Loan`

**Changes (`app/models.py`):**
1. Update imports (around line 6):
   ```python
   from typing import List, Optional
   ```
2. Replace the TODO in the `Loan` class (around line 98):
   ```python
       due_at: Mapped[datetime] = mapped_column(DateTime)
       returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
       late_fee_cents: Mapped[int] = mapped_column(Integer, default=0)
   ```

---

## Commit 2: ISBN-13 Checksum Validation

**Commit Message:**
`feat(schemas): Add ISBN-13 checksum validation to normalize_isbn13`

**Changes (`app/schemas.py`):**
Replace the TODO in `normalize_isbn13` (around line 31):
```python
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn[:12]))
    expected = (10 - total % 10) % 10
    if int(isbn[12]) != expected:
        raise ValueError("isbn checksum is invalid")
    return isbn
```

---

## Commit 3: Email Normalization Fix (AI Trap #1)

**Commit Message:**
`fix(schemas): Ensure normalize_email strips and lowercases before regex check`

**Changes (`app/schemas.py`):**
In `MemberCreate.normalize_email` (around line 106), add normalization *before* the pattern check:
```python
    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Validate and normalize the email address."""
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("email is not valid")
        return value
```

---

## Commit 4: Order Items Validation (AI Trap #2)

**Commit Message:**
`feat(schemas): Add Pydantic model_validator to OrderCreate to reject empty items and duplicate books`

**Changes (`app/schemas.py`):**
Replace the TODO in `OrderCreate` (around line 144) with a `@model_validator`:
```python
class OrderCreate(BaseModel):
    member_id: int
    items: List[OrderItemIn]

    @model_validator(mode="after")
    def validate_items(self) -> "OrderCreate":
        if not self.items:
            raise ValueError("items must not be empty")
        book_ids = [item.book_id for item in self.items]
        if len(book_ids) != len(set(book_ids)):
            raise ValueError("duplicate book_id in items")
        return self
```

---

## Commit 5: Duplicate ISBN Check

**Commit Message:**
`feat(services/books): Reject book creation if ISBN already exists (409)`

**Changes (`app/services/books.py`):**
In `create_book` (around line 17):
```python
    existing = db.scalar(select(Book).where(Book.isbn == data.isbn))
    if existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="A book with this ISBN already exists")
    book = Book(**data.model_dump())
```
*(Also ensure `from sqlalchemy import select` is imported at the top).*

---

## Commit 6: Fix list_books Logic (AI Trap #3)

**Commit Message:**
`fix(services/books): Fix list_books filters, sort logic, and pagination total count`

**Changes (`app/services/books.py`):**
Update `list_books` to fix the 4 bugs (lines 57-68):
```python
    from sqlalchemy import func # Add this to imports at top

    query = select(Book)
    if q:
        query = query.where(
            Book.title.icontains(q, autoescape=True) | Book.author.icontains(q, autoescape=True)
        )
    if restricted is not None:
        query = query.where(Book.restricted == restricted)
    if min_price is not None:
        query = query.where(Book.price_cents >= min_price)
    if max_price is not None:
        query = query.where(Book.price_cents <= max_price)

    if sort == "title":
        query = query.order_by(Book.title.asc(), Book.id.asc())
    elif sort == "-title":
        query = query.order_by(Book.title.desc(), Book.id.asc())
    elif sort == "price":
        query = query.order_by(Book.price_cents.asc(), Book.id.asc())
    elif sort == "-price":
        query = query.order_by(Book.price_cents.desc(), Book.id.asc())
    else:
        query = query.order_by(Book.id.asc())

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    books = db.scalars(query.limit(limit).offset(offset)).all()

    return BookPage(items=books, total=total, limit=limit, offset=offset)
```

---

## Commit 7: Implement Partial Book Updates

**Commit Message:**
`feat(books): Expose PATCH /books/{id} and implement update_book service`

**Changes (`app/services/books.py`):**
Implement `update_book` (around line 33):
```python
def update_book(db: Session, book_id: int, data: BookUpdate) -> Book:
    book = get_book(db, book_id)
    for field in data.model_fields_set:
        if field == "isbn":
            continue
        setattr(book, field, getattr(data, field))
    db.commit()
    db.refresh(book)
    return book
```
**Changes (`app/routers/books.py`):**
Add import `BookUpdate` and expose route (around line 46):
```python
@router.patch("/{book_id}", response_model=BookOut)
def update_book(book_id: int, data: BookUpdate, db: Session = Depends(get_db)):
    return service.update_book(db, book_id, data)
```

---

## Commit 8: Fix tier_at_least Logic (AI Trap #4)

**Commit Message:**
`fix(services/members): Fix off-by-one bug in tier_at_least helper`

**Changes (`app/services/members.py`):**
Change strict `>` to `>=` in `tier_at_least` (around line 26):
```python
def tier_at_least(tier: str, minimum: str) -> bool:
    """True if ``tier`` ranks at or above ``minimum``."""
    return TIER_ORDER.index(tier) >= TIER_ORDER.index(minimum)
```

---

## Commit 9: Enforce Unique Member Emails

**Commit Message:**
`feat(services/members): Reject member creation if email is already in use (409)`

**Changes (`app/services/members.py`):**
In `create_member` (around line 42):
```python
    existing = db.scalar(select(Member).where(Member.email == data.email))
    if existing:
        raise HTTPException(status_code=409, detail="A member with this email already exists")
    member = Member(name=data.name, email=data.email, tier=data.tier.value, created_at=now)
```

---

## Commit 10: Implement Member Stats

**Commit Message:**
`feat(services/members): Implement get_member_stats aggregating paid orders and active/overdue loans`

**Changes (`app/services/members.py`):**
Import `Loan` and `OrderStatus` at top, then implement `get_member_stats`:
```python
def get_member_stats(db: Session, member_id: int, now: datetime) -> MemberStats:
    member = get_member(db, member_id)

    paid_orders = list(db.scalars(
        select(Order).where(Order.member_id == member_id, Order.status == OrderStatus.PAID.value)
    ))
    orders_paid = len(paid_orders)
    total_spent_cents = sum(o.total_cents for o in paid_orders)

    all_loans = list(db.scalars(
        select(Loan).where(Loan.member_id == member_id)
    ))
    unreturned = [l for l in all_loans if l.returned_at is None]
    active_loans = len(unreturned)
    overdue_loans = len([l for l in unreturned if now > l.due_at])
    late_fees_cents = sum(l.late_fee_cents for l in all_loans if l.returned_at is not None)

    return MemberStats(
        member_id=member_id,
        orders_paid=orders_paid,
        total_spent_cents=total_spent_cents,
        active_loans=active_loans,
        overdue_loans=overdue_loans,
        late_fees_cents=late_fees_cents,
    )
```

---

## Commit 11: Calculate Discount Percent

**Commit Message:**
`feat(services/orders): Implement calculate_discount_percent with tier and bulk logic`

**Changes (`app/services/orders.py`):**
Implement `calculate_discount_percent` (around line 24):
```python
def calculate_discount_percent(member: Member, total_quantity: int) -> int:
    pct = TIER_DISCOUNT_PERCENT[member.tier]
    if total_quantity >= BULK_QUANTITY_THRESHOLD:
        pct += BULK_DISCOUNT_PERCENT
    return pct
```

---

## Commit 12: Implement create_order

**Commit Message:**
`feat(services/orders): Implement create_order with restricted access and stock validation`

**Changes (`app/services/orders.py`):**
Implement `create_order` (around line 29):
```python
def create_order(db: Session, data: OrderCreate, now: datetime) -> Order:
    from app.models import OrderItem
    from app.services.members import get_member, ensure_can_access_restricted
    from app.services.books import get_book

    member = get_member(db, data.member_id)
    books = {}
    for item in data.items:
        books[item.book_id] = get_book(db, item.book_id)

    for item in data.items:
        if books[item.book_id].restricted:
            ensure_can_access_restricted(member)
            break

    for item in data.items:
        book = books[item.book_id]
        if book.stock < item.quantity:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for '{book.title}'")

    order_items = []
    for item in data.items:
        book = books[item.book_id]
        book.stock -= item.quantity
        order_items.append(OrderItem(
            book_id=item.book_id,
            quantity=item.quantity,
            unit_price_cents=book.price_cents,
        ))

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
```

---

## Commit 13: Fix cancel_order Stock Restore (AI Trap #5)

**Commit Message:**
`fix(services/orders): Ensure cancel_order properly restores reserved book stock`

**Changes (`app/services/orders.py`):**
In `cancel_order` (around line 68), add the stock restoration loop before commit:
```python
    order.status = OrderStatus.CANCELLED.value
    for item in order.items:
        item.book.stock += item.quantity
    db.commit()
```

---

## Commit 14: Loan Status & Late Fee Helpers (AI Trap #6)

**Commit Message:**
`feat(services/loans): Implement loan_status, to_loan_out, and calculate_late_fee helpers`

**Changes (`app/services/loans.py`):**
Implement `loan_status` (line 22), `to_loan_out` (line 27), and `calculate_late_fee` (line 32):
```python
def loan_status(loan: Loan, now: datetime) -> LoanStatus:
    if loan.returned_at is not None:
        return "returned"
    if now > loan.due_at:
        return "overdue"
    return "active"

def to_loan_out(loan: Loan, now: datetime) -> LoanOut:
    return LoanOut(
        id=loan.id,
        member_id=loan.member_id,
        book_id=loan.book_id,
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        late_fee_cents=loan.late_fee_cents,
        status=loan_status(loan, now),
    )

def calculate_late_fee(due_at: datetime, returned_at: datetime, price_cents: int) -> int:
    if returned_at <= due_at:
        return 0
    seconds_late = (returned_at - due_at).total_seconds()
    import math
    days_late = math.ceil(seconds_late / 86400)
    return min(days_late * LATE_FEE_PER_DAY_CENTS, price_cents)
```

---

## Commit 15: Create Loan Endpoint

**Commit Message:**
`feat(services/loans): Implement create_loan enforcing restrictions, limits and stock`

**Changes (`app/services/loans.py`):**
Import `HTTPException` and `select` at top. Implement `create_loan` (line 37):
```python
def create_loan(db: Session, data: LoanCreate, now: datetime) -> LoanOut:
    from app.services.members import get_member, ensure_can_access_restricted
    from app.services.books import get_book

    member = get_member(db, data.member_id)
    book = get_book(db, data.book_id)

    if book.restricted:
        ensure_can_access_restricted(member)

    member_loans = list(db.scalars(
        select(Loan).where(Loan.member_id == data.member_id, Loan.returned_at == None)
    ))
    for loan in member_loans:
        if now > loan.due_at:
            raise HTTPException(status_code=409, detail="Member has an overdue loan")

    for loan in member_loans:
        if loan.book_id == data.book_id:
            raise HTTPException(status_code=409, detail="Member already has this book on loan")

    limit = TIER_LOAN_LIMIT[member.tier]
    if limit is not None and len(member_loans) >= limit:
        raise HTTPException(status_code=409, detail="Member has reached their loan limit")

    if book.stock == 0:
        raise HTTPException(status_code=409, detail="Book is out of stock")

    loan = Loan(
        member_id=data.member_id,
        book_id=data.book_id,
        borrowed_at=now,
        due_at=now + LOAN_PERIOD,
        returned_at=None,
        late_fee_cents=0,
    )
    book.stock -= 1
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return to_loan_out(loan, now)
```

---

## Commit 16: Get, Return, and List Member Loans

**Commit Message:**
`feat(services/loans): Implement get_loan, return_loan with fees, and list_member_loans`

**Changes (`app/services/loans.py`):**
Implement `get_loan`, `return_loan`, and `list_member_loans` (lines 53–71):
```python
def get_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    return to_loan_out(loan, now)


def return_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.returned_at is not None:
        raise HTTPException(status_code=409, detail="Loan already returned")

    loan.returned_at = now
    loan.late_fee_cents = calculate_late_fee(loan.due_at, now, loan.book.price_cents)
    loan.book.stock += 1
    db.commit()
    db.refresh(loan)
    return to_loan_out(loan, now)


def list_member_loans(
    db: Session, member_id: int, now: datetime, status: Optional[LoanStatus] = None
) -> List[LoanOut]:
    from app.services.members import get_member
    get_member(db, member_id)

    loans = list(db.scalars(
        select(Loan).where(Loan.member_id == member_id).order_by(Loan.id.asc())
    ))
    result = [to_loan_out(loan, now) for loan in loans]
    if status is not None:
        result = [l for l in result if l.status == status]
    return result
```

---

## Commit 17: Top Books Report

**Commit Message:**
`feat(services/reports): Implement top_books SQL aggregation report`

**Changes (`app/services/reports.py`):**
Implement `top_books` (around line 9):
```python
def top_books(db: Session, limit: int = 5) -> List[TopBook]:
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
```

---

> [!SUCCESS]
> After completing these 17 commits sequentially, your repository will be perfectly layered with incremental, logical Git history and all 202/202 tests will pass!
