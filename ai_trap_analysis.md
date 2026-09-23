# AI Trap Analysis — Sanctum Sanctorum Repository

After auditing every file and every line in the repository, I found **17 deliberate traps** across 5 categories. These are patterns specifically designed to catch AI agents that blindly generate code without deeply understanding the spec, the tests, and the existing code's subtle bugs.

---

## Category 1: 🐛 Poisoned Existing Code ("Trust the Code" Traps)

These traps plant **working-looking but subtly broken code** that an AI will blindly trust and build on top of.

---

### Trap 1: `tier_at_least` uses `>` instead of `>=`

**Location:** [services/members.py:26](file:///e:/Sanctum-Sanctorum-main/app/services/members.py#L24-L26)

```python
def tier_at_least(tier: str, minimum: str) -> bool:
    """True if ``tier`` ranks at or above ``minimum``."""
    return TIER_ORDER.index(tier) > TIER_ORDER.index(minimum)  # BUG: should be >=
```

**The trap:** The docstring says "at or above" but the code uses strict `>`. A `master`-tier member checking against `RESTRICTED_MIN_TIER = "master"` returns `False` (2 > 2 is False). An AI that trusts existing helper functions will propagate this bug — **every restricted-access test for master-tier members will fail** (both orders and loans).

**What tests catch it:**
- `test_restricted_book_allowed_for_master_and_above[master]` (orders)
- `test_restricted_book_allowed_for_master_and_above[master]` (loans)

**The frontend proves the intent:** [app.js:1076](file:///e:/Sanctum-Sanctorum-main/frontend/app.js#L1076) correctly uses `>=`:
```js
TIERS.indexOf(tier) >= TIERS.indexOf('master') ? 'Allowed' : 'Master tier required'
```

> [!CAUTION]
> This is the most dangerous trap in the repo. The function is fully written, has a correct-looking docstring, and is used by `ensure_can_access_restricted`. An AI will never question it.

---

### Trap 2: `cancel_order` — Docstring says "restores stock" but the code doesn't

**Location:** [services/orders.py:68–76](file:///e:/Sanctum-Sanctorum-main/app/services/orders.py#L68-L76)

```python
def cancel_order(db: Session, order_id: int) -> Order:
    """Cancel a pending order and restore the reserved stock. ..."""
    order = get_order(db, order_id)
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(...)
    order.status = OrderStatus.CANCELLED.value
    db.commit()         # ← stock is NOT restored!
    db.refresh(order)
    return order
```

**The trap:** The function looks "done" — it has error handling, status change, commit, refresh, and return. An AI that scans for `NotImplementedError` will skip right past this function. But the docstring explicitly says "restore the reserved stock" and the code never touches `item.book.stock`.

**What tests catch it:**
- `test_cancel_restores_stock_of_every_item` — asserts stock goes back to original
- `test_cancel_twice_returns_409_and_does_not_restore_again` — asserts stock=10, not 13 (which would happen if stock is restored twice)

---

### Trap 3: `list_books` `q` filter only searches `title`, not `title OR author`

**Location:** [services/books.py:58–59](file:///e:/Sanctum-Sanctorum-main/app/services/books.py#L58-L59)

```python
if q:
    query = query.where(Book.title.icontains(q, autoescape=True))
    #                   ^^^^ ONLY title — spec says title OR author
```

**The trap:** This is partial implementation that "works" for title searches. An AI extending this function would focus on the TODOs for `min_price`/`max_price`/`sort` and **never revisit the `q` filter** that's already written. There's no TODO comment on this line.

**What tests catch it:**
- `test_q_matches_author_case_insensitively`
- `test_q_matches_title_or_author` (asserts total == 2, matching both title and author hits)

---

## Category 2: 📝 Misleading / Incomplete TODOs

These traps use TODO comments that **point to some bugs but deliberately omit others** in the same function.

---

### Trap 4: `list_books` — TODOs mention sort and price, but hide TWO other bugs

**Location:** [services/books.py:62–66](file:///e:/Sanctum-Sanctorum-main/app/services/books.py#L62-L66)

```python
    # TODO: min_price / max_price filters     ← mentioned
    # TODO: apply ``sort``                     ← mentioned
    books = db.scalars(query.order_by(Book.id.asc()).limit(limit).offset(offset)).all()
    total = len(books)                         # ← BUG: not mentioned in any TODO
```

**Hidden bugs not called out by any TODO:**
1. **`q` only matches title** (Trap 3 above)
2. **`total = len(books)` is calculated AFTER pagination** — the spec says `total` = count matching filters BEFORE `limit`/`offset`. With 21 books and limit=20, this returns `total=20` instead of `total=21`.

**What tests catch it:**
- `test_default_limit_is_20` — creates 21 books, expects `total=21` with only 20 items
- `test_offset_past_end_returns_no_items_but_total` — expects `total=2` even with 0 items
- `test_total_counts_filtered_results_before_pagination` — explicitly tests this exact scenario

---

### Trap 5: `schemas.py` OrderCreate — TODO tells you WHAT but not WHERE

**Location:** [schemas.py:144](file:///e:/Sanctum-Sanctorum-main/app/schemas.py#L144)

```python
class OrderCreate(BaseModel):
    member_id: int
    # TODO: reject an empty items list and the same book_id appearing twice (both 422)
    items: List[OrderItemIn]
```

**The trap:** The TODO says to reject these, but doesn't say HOW. An AI might add the check in the **service** instead of the **schema**. But the test `test_422_checked_before_missing_member` sends a duplicate book with a non-existent member (id=9999) and expects **422**, not 404. If the duplicate check is in the service, the service would hit the 404 member-not-found check first. The validation MUST be a `@model_validator` in the schema so Pydantic rejects it before the service runs.

---

### Trap 6: `schemas.py` email validator — looks complete but isn't

**Location:** [schemas.py:106–112](file:///e:/Sanctum-Sanctorum-main/app/schemas.py#L106-L112)

```python
@field_validator("email")
@classmethod
def normalize_email(cls, value: str) -> str:
    """Validate and normalize the email address."""
    if not EMAIL_PATTERN.match(value):
        raise ValueError("email is not valid")
    return value    # ← returns value WITHOUT stripping or lowercasing
```

**The trap:** The method is named `normalize_email` and the docstring says "normalize". It has no TODO comment. An AI that sees "normalize" + working pattern check will assume it's done. But the spec says "stripped + lowercased" and the test sends `"  Stephen.Strange@Sanctum.ORG  "` expecting `"stephen.strange@sanctum.org"`.

**The cascading trap:** Without lowercasing, the duplicate-email-case-insensitive test (`test_duplicate_email_is_case_insensitive`) also fails because `"wong@sanctum.org"` and `"WONG@Sanctum.org"` are stored as different strings, so the 409 uniqueness check never fires.

---

## Category 3: 🧩 Schema-Level Gotchas

These are structural patterns in the Pydantic schemas designed to catch AIs that follow patterns without understanding them.

---

### Trap 7: `LoanOut` deliberately MISSING `from_attributes=True`

**Location:** [schemas.py:181–189](file:///e:/Sanctum-Sanctorum-main/app/schemas.py#L181-L189)

```python
class LoanOut(BaseModel):        # ← NO model_config = ConfigDict(from_attributes=True)
    id: int
    member_id: int
    ...
    status: LoanStatus           # ← NOT a database column
```

Compare with every other `*Out` schema:
```python
class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # ← has it
class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # ← has it
class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # ← has it
class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # ← has it
```

**The trap:** An AI following the established pattern will add `from_attributes=True` to `LoanOut` and try to return the ORM `Loan` object directly from the service. This BREAKS because:
1. `status` is a **computed field** (not stored in the DB), so Pydantic can't read it from the ORM object
2. The service must **manually construct** `LoanOut` via the `to_loan_out()` helper with the computed status

This is why `to_loan_out()` exists as a separate function — it's the only `*Out` schema that requires manual assembly.

---

### Trap 8: `BookUpdate.reject_explicit_nulls` and `model_fields_set`

**Location:** [schemas.py:68–73](file:///e:/Sanctum-Sanctorum-main/app/schemas.py#L68-L73)

```python
@model_validator(mode="after")
def reject_explicit_nulls(self) -> BookUpdate:
    for name in self.model_fields_set:
        if getattr(self, name) is None:
            raise ValueError(f"{name} may not be null")
    return self
```

**The trap:** An AI implementing `update_book` might iterate over ALL fields and check `if value is not None`, which would skip fields explicitly set to valid falsy values like `price_cents=0` or `restricted=False`. The correct approach is to iterate over `data.model_fields_set` — only fields explicitly sent in the request body. This validator exists to hint at the pattern but an AI might not connect the dots.

---

### Trap 9: `isbn` silently ignored on PATCH — not in `BookUpdate` at all

**Location:** `BookUpdate` class has no `isbn` field. The spec says "if sent it is *silently ignored*, not rejected."

**The trap:** An AI might:
- Add `isbn` validation to the PATCH endpoint (WRONG — should be silently ignored)
- Add `isbn: Optional[str] = None` to `BookUpdate` and then skip it (UNNECESSARY — Pydantic v2 ignores unknown fields by default)

The test `test_isbn_is_ignored` sends `{"isbn": "...", "stock": 1}` and expects 200 with only stock changed and the original ISBN preserved. Pydantic's default `extra='ignore'` behavior handles this correctly with no extra code.

---

### Trap 10: `OrderItemOut.line_total_cents` reads an `@property`, not a column

**Location:** [models.py:86–88](file:///e:/Sanctum-Sanctorum-main/app/models.py#L86-L88)

```python
@property
def line_total_cents(self) -> int:
    return self.unit_price_cents * self.quantity
```

**The trap:** `line_total_cents` is a `@property` on the ORM model, not a database column. `OrderItemOut` has `from_attributes=True` which enables Pydantic to read properties. An AI might try to add `line_total_cents` as a database column, or compute it separately in the service, or forget to include it entirely. The existing design is correct — the property + `from_attributes=True` handles it automatically.

---

## Category 4: 📋 Spec-vs-Intuition Traps

These traps have specs/tests that contradict what "feels right."

---

### Trap 11: Validation check ORDER is strictly enforced

**The spec (Orders):**
> Checks in this order: 1. 422... 2. 404 member... 3. 403 restricted... 4. 409 stock

**The spec (Loans):**
> Checks in order: 1. 404 member... 2. 403 restricted... 3. 409 overdue... 4. 409 same book... 5. 409 limit... 6. 409 stock

**The trap:** Tests enforce the EXACT ordering, not just the outcomes:

| Test | Sends | Expects | Tests which check fires first |
|---|---|---|---|
| `test_422_checked_before_missing_member` | duplicate book + member 9999 | 422 | 422 before 404 |
| `test_404_checked_before_restricted` | restricted book + book 9999 | 404 | 404 before 403 |
| `test_403_checked_before_insufficient_stock` | restricted + qty > stock | 403 | 403 before 409 |
| `test_403_checked_before_overdue` (loans) | overdue + restricted | 403 | 403 before 409 |

An AI that checks stock before member, or restricted before loading all books, will fail these ordering tests.

---

### Trap 12: Overdue boundary is **strict `>`**, not `>=`

**The spec:**
> The boundary is strict: at exactly `due_at` a loan is still `active`, is not overdue anywhere (including in member stats), and owes no late fee.

**The trap:** An AI will instinctively use `>=` for "past due" because `due_at` sounds like a deadline. But:
- `loan_status`: `now > due_at` → overdue (strict `>`)
- `create_loan` overdue check: `now > loan.due_at` (strict `>`)
- `get_member_stats` overdue count: `now > l.due_at` (strict `>`)
- `calculate_late_fee`: `returned_at <= due_at` → fee = 0 (at exactly due_at, no fee)

**Three separate tests enforce this:**
- `test_loan_due_right_now_does_not_block_borrowing` — borrows at exactly due_at, expects 201
- `test_status_is_active_until_due` — at exactly due_at, status is "active"
- `test_loan_due_exactly_now_counts_as_active_not_overdue` — at exactly due_at, overdue_loans = 0

---

### Trap 13: Late fee uses book's CURRENT price, not price at borrow time

**The spec:**
> late_fee_cents = min(days_late × 25, book.price_cents), **using the book's price at the time of return**.

**The trap:** Orders snapshot prices at creation (`unit_price_cents`). An AI might assume loans do the same. But the late fee cap uses `book.price_cents` — the **current** price from the database at the moment of return. If the book's price was changed between borrowing and returning, the new price is used for the fee cap.

---

### Trap 14: Sort tiebreaker is ALWAYS `id ASC`, even for descending sorts

**The spec:**
> ties broken by id ascending

**The trap:** For `sort=-price` (descending), ties should still be broken by `id ASC`, not `id DESC`. An AI might mirror the sort direction for the tiebreaker.

**Test `test_sort_by_price_descending_with_id_tie_break`:**
```python
expensive1 = make_book(price_cents=300)   # id=3
expensive2 = make_book(price_cents=300)   # id=4
assert ids(response) == [expensive1["id"], expensive2["id"], ...]
# expensive1 (id=3) before expensive2 (id=4), even though sort is DESC
```

---

## Category 5: 🔢 Arithmetic / Boundary Traps

---

### Trap 15: Late fee uses `ceil()`, not `floor()` or integer division

**The spec:**
> days_late = ceil((now − due_at) / 1 day) (any partial day counts as a full day)

**The trap:** An AI might use `timedelta.days` (which truncates) or `//` (floor division). But the test:

```python
(timedelta(days=17, hours=1), 100),  # 3 days + 1 hour late → 4 days
```

`timedelta(days=17, hours=1) - timedelta(days=14)` = 3 days + 1 hour. `timedelta.days` would give 3. `ceil(3.0417)` gives 4. Fee = 4 × 25 = 100.

Also tricky: `timedelta(days=14, seconds=1)` → `ceil(1/86400) = ceil(0.0000116) = 1` day → 25 cents.

The correct implementation must use `math.ceil(total_seconds / 86400)`.

---

### Trap 16: Discount uses floor division (`//`), not rounding

**The spec:**
> discount_cents = subtotal × discount_percent // 100 (floor)

**Test `test_discount_is_rounded_down`:**
```python
# book price_cents=999, adept tier (5%)
# 999 * 5 / 100 = 49.95 → 49 (floor, not round)
assert body["discount_cents"] == 49
assert body["total_cents"] == 950   # 999 - 49 = 950
```

An AI that uses `round()` instead of `//` would compute 50, getting total_cents=949.

---

### Trap 17: `total_spent_cents` in stats requires correct discount math

**Test `test_order_stats_count_only_paid_orders`:**
```python
member = make_member(tier="supreme")  # 15% discount
book = make_book(price_cents=1000)

order(2) → pay   # subtotal=2000, discount=15%=300, total=1700
order(1) → pay   # subtotal=1000, discount=15%=150, total=850
order(3)          # pending — NOT counted
order(4) → cancel # cancelled — NOT counted

assert stats["total_spent_cents"] == 2550  # 1700 + 850
```

**The trap:** Getting `2550` requires getting THREE things right simultaneously:
1. Correct tier discount percentage (15% for supreme)
2. Floor division for discount (`1000 * 15 // 100 = 150`, not `round(150.0)`)
3. Only counting `paid` orders (not pending or cancelled)

If any of these is wrong, the number won't match.

---

## Summary

| # | Trap | Category | Danger Level | File |
|---|---|---|---|---|
| 1 | `tier_at_least` `>` vs `>=` | Poisoned code | 🔴 Critical | services/members.py:26 |
| 2 | `cancel_order` doesn't restore stock | Poisoned code | 🔴 Critical | services/orders.py:68-76 |
| 3 | `q` only searches title, not author | Poisoned code | 🟡 High | services/books.py:59 |
| 4 | `total = len(books)` after pagination + hidden bugs | Incomplete TODO | 🟡 High | services/books.py:62-66 |
| 5 | OrderCreate validation must be in SCHEMA not service | Incomplete TODO | 🟡 High | schemas.py:144 |
| 6 | `normalize_email` doesn't strip/lowercase | Incomplete TODO | 🟡 High | schemas.py:106-112 |
| 7 | `LoanOut` missing `from_attributes` BY DESIGN | Schema gotcha | 🔴 Critical | schemas.py:181-189 |
| 8 | `model_fields_set` partial update pattern | Schema gotcha | 🟡 High | schemas.py:68-73 |
| 9 | `isbn` silently ignored, not rejected | Schema gotcha | 🟢 Medium | BookUpdate schema |
| 10 | `line_total_cents` is a `@property` | Schema gotcha | 🟢 Medium | models.py:86-88 |
| 11 | Validation check ORDER strictly enforced | Spec vs intuition | 🔴 Critical | SPEC.md + 4 tests |
| 12 | Overdue boundary strict `>` not `>=` | Spec vs intuition | 🔴 Critical | SPEC.md + 3 tests |
| 13 | Late fee uses CURRENT price, not snapshot | Spec vs intuition | 🟡 High | SPEC.md |
| 14 | Sort tiebreaker always `id ASC` | Spec vs intuition | 🟢 Medium | SPEC.md + tests |
| 15 | Late fee uses `ceil()` not `floor()` | Arithmetic | 🔴 Critical | SPEC.md + 5 tests |
| 16 | Discount uses floor (`//`) not `round()` | Arithmetic | 🟡 High | SPEC.md + 1 test |
| 17 | Stats `total_spent_cents` = compound trap | Arithmetic | 🟡 High | test_members.py:127 |

---

## Meta-Observation

This assignment is **brilliantly designed** as an AI-detection system. The traps fall into a clear pattern:

1. **"Trust existing code" traps** (1, 2, 3) — AI agents trust written code and only look for `NotImplementedError` or TODO comments
2. **"Follow the pattern" traps** (7, 8, 9, 10) — AI agents copy patterns from adjacent code without understanding why a pattern is broken deliberately
3. **"Spec says one thing, intuition says another" traps** (11, 12, 13, 14) — AI agents use common sense instead of reading the spec precisely
4. **"Incomplete breadcrumbs" traps** (4, 5, 6) — TODOs call out SOME bugs but hide others in the same function

The assignment evaluators can likely tell AI-generated code by checking whether the submission falls for these specific traps, particularly:
- Does `tier_at_least` get fixed? (only someone who traces through the test failures would find it)
- Does `cancel_order` restore stock? (only someone who reads the docstring vs code would notice)
- Is `LoanOut` manually constructed? (only someone who understands why `from_attributes` is absent would get it right)
