# NOTES — Nishant Sahni's Submission - Sanctum Sanctorum Bookstore

## Contents

- [Live deployment](#live-deployment)
- [Status](#status)
- [Architecture and design decisions](#architecture-and-design-decisions)
  - [Layering](#layering)
  - [Validation](#validation)
  - [Pagination](#pagination)
  - [Domain model](#domain-model)
  - [Business rules](#business-rules)
  - [Data integrity and concurrency](#data-integrity-and-concurrency)
- [Deployment](#deployment)
- [Spec ambiguities and things I noticed](#spec-ambiguities-and-things-i-noticed)
- [Known gaps and what I'd do with more time](#known-gaps-and-what-id-do-with-more-time)
- [Git history](#git-history)
- [AI usage](#ai-usage)

## Live deployment

- **App:** https://sanctumsanctorum.onrender.com/ (UI at `/`, Swagger at `/docs`, health at `/health`)
- **The first load may take about a minute.** The app runs on Render's free tier, which sleeps after 15 minutes without traffic. If the header briefly shows "API unreachable" while it wakes up, refresh once.
- **Signing in:** there are no passwords. "Sign in as member" selects which member the UI acts as, by ID. The seeded members cover every tier:

| ID | Name | Email | Tier | Useful for testing |
|---|---|---|---|---|
| 1 | Wong Li | wong@example.com | supreme | 15% discount, unlimited loans, restricted books |
| 2 | Christine Palmer | christine@example.com | master | 10% discount, restricted books (lowest tier allowed) |
| 3 | Jonathan Pangborn | jonathan@example.com | adept | 5% discount, 403 on restricted books |
| 4 | Sara Lin | sara@example.com | apprentice | no discount, one-loan limit |

- *Darkhold* is a restricted seeded book. Ordering 10 or more copies in total adds a 5% bulk discount on top of the tier discount.
- The database was reset to the seed data just before submission. There is no authentication (see Known gaps), so anything you change is visible to anyone with the URL.

## Status

**Finished**

- All five feature areas in SPEC.md: books, members, orders, loans, and member stats and reports. Every endpoint and rule in the spec is implemented.
- `uv run pytest`: 213 passed. That is the original 202, with no existing test file modified, plus 11 of my own in a new file, `tests/test_edge_cases.py`. The suite runs on the default in-memory SQLite with no external services; I checked this in a fresh terminal with no database URL set.
- All three optional extras:
  - Concurrent orders for the last copy of a book are handled safely, and the same fix covers loans (see Data integrity and concurrency).
  - `GET /members` with pagination.
  - Edge-case tests. The new file covers `GET /members` defaults, slicing and invalid bounds; the late-fee cap when a book's price drops during a loan; the `due_at` boundary, both exactly at it and one second past; a borrowed last copy blocking an order; literal `%` and `_` in search; and an explicit `null` in `PATCH /books/{id}`. Candidates the existing suite already covered were skipped.
- Two further fixes from my own review: simultaneous duplicate ISBNs or emails now return 409 instead of 500, and money, stock and quantity columns are 64-bit.

**Not done:** nothing from the optional extras. The remaining gaps are listed under Known gaps.

**Tests I think are wrong:** none.

## Architecture and design decisions

### Layering

- Routers are thin: they parse the request, call one service function and return the result. Every business rule lives in `app/services/`.
- Services raise `HTTPException` directly for 404, 403 and 409. Trade-off: services know about HTTP. The cleaner alternative is small domain exceptions mapped to status codes in `main.py`; the spec allows either, and at this size raising directly keeps each rule next to its status code.
- Anything that needs the current time gets it from the `get_now` dependency, never `datetime.now()`, so the clock is injectable and the tests are deterministic.

### Validation

- Input rules live in the Pydantic schemas, so malformed input gets a 422 before any service code runs: ISBN normalisation and ISBN-13 checksum (`normalize_isbn13`), strip-then-measure lengths for titles, authors and names, email strip, lowercase and regex check, order quantity of at least 1, a non-empty item list, and no duplicate `book_id` within an order.
- Checks that need the database live in the services: duplicate ISBN or email (409) and missing entities (404).
- Query parameters are validated at the router: `limit` (1–100) and `offset` (≥ 0) through `Query` on both `GET /books` and `GET /members`, and `sort` through a `Literal` type, so any other value, including `id`, is a 422 with no custom code.
- `PATCH /books/{id}`: fields that aren't sent stay unchanged, `isbn` and unknown fields are silently ignored as the spec requires, and an explicit `null` is rejected (see Spec ambiguities).

### Pagination

- `GET /members` has no spec, so it mirrors `GET /books`: the same `limit` and `offset` bounds, `total` counted before pagination, ordering by id, and no filters.
- Both endpoints return one generic `Page[T]` schema (`items`, `total`, `limit`, `offset`). `BookPage` and `MemberPage` are aliases of it, so the `GET /books` response is unchanged.
- The count-then-slice logic is three lines, repeated in the books and members services rather than extracted into a shared helper. With two callers, a helper would couple the two services for little gain; I'd extract it at a third.

### Domain model

- Added the missing `Loan` model, with a nullable `returned_at` and `late_fee_cents` defaulting to 0.
- Loan status (`active`, `overdue`, `returned`) is computed when read and never stored. Trade-off: it can never go stale and needs no scheduled job, but the database can't filter on it, so `GET /members/{id}/loans?status=` filters in Python. That's fine at this scale; at larger scale I'd translate each status into its SQL condition.
- `line_total_cents` is a computed property on `OrderItem` rather than a stored column, so it can never disagree with unit price × quantity.
- `unit_price_cents` is copied onto each order item when the order is placed, so later price changes don't rewrite past orders.
- Money, stock and quantity columns are `BigInteger`. Postgres `INTEGER` is 32-bit while SQLite's is 64-bit, so without this the two databases accepted different ranges. Primary and foreign keys stay `Integer`.
- Tiers and order statuses are enums. Tier comparisons use each tier's position in an ordered list, through `tier_at_least`.

### Business rules

- Order and loan creation run their checks in exactly the order the spec lists. This matters when a request fails several checks at once: a restricted book that is also out of stock returns 403, not 409.
- Discounts come from a tier table plus two bulk constants (`BULK_QUANTITY_THRESHOLD = 10`, `BULK_DISCOUNT_PERCENT = 5`), with `discount_cents = subtotal * percent // 100` (floor).
- Late fees are 25¢ per day, any partial day counts as a whole day, and the total is capped at the book's price **at return time**.
- Loan limits are a lookup table in which `None` means unlimited (supreme).
- The `due_at` boundary is strict everywhere: at exactly `due_at` a loan is still active, doesn't count as overdue in member stats, and owes no fee.
- The top-books report is a single SQL aggregation rather than a Python loop: order items joined to orders and books, paid orders only, zero-sales books excluded, sorted by copies sold then title, using each book's current title.
- Book search uses `icontains(..., autoescape=True)`. This escapes `%` and `_` so that a search for `50%` matches that literal text. It is **not** SQL-injection protection; SQLAlchemy already sends the search term as a bound parameter.

### Data integrity and concurrency

The spec requires that a failed order leaves stock untouched. Checking stock in Python and then writing it back is correct for one request at a time, but two simultaneous requests can both pass the check. Orders and loans therefore leave those decisions to the database:

- **Shared stock helpers.** `reserve_stock` and `release_stock` live in `app/services/books.py`, because stock belongs to books, and both the orders and loans services call them. Reserving is one statement, `UPDATE books SET stock = stock - :qty WHERE id = :id AND stock >= :qty`, followed by a row-count check. Releasing increments `stock = stock + :qty` in SQL, so two concurrent releases to the same book can't overwrite each other.
- **Placing an order** reserves each item in turn. On the first shortfall the service rolls back, which also undoes the reservations already made for earlier items in the same order. The separate Python pre-check was removed, so the database is the single source of truth.
- The rollback is explicit, even though closing the session would roll back too, so the all-or-nothing guarantee is visible in the service instead of depending on `get_db` teardown.
- **Paying and cancelling** only update an order `WHERE status = 'pending'`. Two simultaneous cancels can't both restore stock, and a pay and a cancel can't both succeed. When the update matches nothing, the order is reloaded so the 409 message reports the status that was actually committed.
- **Borrowing** reserves one copy at the point where the spec's "stock is 0" check sits, so the check order is unchanged.
- **Returning** marks the loan returned with one guarded `UPDATE ... WHERE returned_at IS NULL`, with the late fee computed beforehand, and releases the copy only if that update matched a row. Two simultaneous returns can't restore stock twice or charge the fee twice.
- **Duplicates:** `create_book` and `create_member` keep their look-up for the normal case, and also catch the `IntegrityError` raised by the database's unique constraint on `isbn` or `email`, then roll back and return the same 409. It's caught in these two functions rather than by a global handler in `main.py`, which would disguise unrelated integrity bugs, such as a foreign-key violation, as client conflicts.
- **Why this works:** on Postgres the `UPDATE` locks the row, and a concurrent `UPDATE` waits, then re-checks its `WHERE` clause against the committed value, so the second request matches zero rows. SQLite allows one writer at a time, so the test suite behaves exactly as before.
- **What isn't tested:** none of these races has an automated test. The in-memory SQLite test database can't reproduce Postgres row locking, and `conftest.py`, which I can't change, exposes no database session for forcing a duplicate insert (see Known gaps).

## Deployment

**Stack: Render (web service) and Neon (Postgres).** I didn't use the suggested Supabase and Vercel:

- Supabase pauses free projects after about a week of low database activity, and you may open the app after a quiet week.
- Render's own free Postgres expires 30 days after creation.
- Vercel runs Python as serverless functions and needs an ASGI adapter; Render simply runs `uvicorn`.
- Neon's free tier suspends compute after 5 minutes idle and wakes it on the next connection, but never expires.

**Configuration**

- Render reads `.python-version` (3.12) and uses uv automatically because `uv.lock` is committed. The build command is `uv sync --frozen --no-dev` and the start command is `uv run --frozen --no-dev uvicorn app.main:app --host 0.0.0.0 --port $PORT`. `--no-dev` in both keeps pytest and httpx off the server, and `--frozen` makes a stale lockfile fail the build instead of being silently re-resolved.
- Render's health check points at `/health`.
- The app and the database are both in Singapore. Every request makes several database round-trips, so keeping them together matters more than distance to the user.
- The app uses Neon's direct connection rather than its pooler: there is one app instance, and SQLAlchemy already pools connections.
- `SANCTUM_DATABASE_URL` is set only in Render's environment settings, using the `postgresql+psycopg://` scheme; without it SQLAlchemy looks for psycopg2. The Git history contains no connection string.

**Code changes for Postgres**

- Added `psycopg[binary]` as the Postgres driver (see Spec ambiguities for the conflict with "no new dependencies").
- `app/db.py` now chooses engine options by database type: `check_same_thread=False` only for SQLite, since psycopg rejects it, and `pool_pre_ping=True` for Postgres. Neon drops open connections when it suspends, so without pre-ping the first request after an idle spell would get a dead pooled connection and fail.
- The test suite is unaffected, because `conftest.py` builds its own in-memory SQLite engine.
- The app creates tables with `create_all` on startup, which never alters existing tables. After the switch to 64-bit columns I recreated the live schema and let the app reseed it, rather than altering columns by hand.

**SQLite vs Postgres differences I checked**

- The seed data doesn't set explicit IDs, so Postgres sequences stay in step and new rows don't collide with seeded ones.
- Postgres enforces `VARCHAR(n)` lengths and 32-bit `INTEGER` limits; SQLite enforces neither. The integer difference is why money, stock and quantity columns are now `BigInteger`.
- Postgres is stricter about `GROUP BY`, which matters for the top-books query, and `icontains` becomes `ILIKE`.
- I smoke-tested against the live database: creating, paying and cancelling orders; a second cancel (409); ordering more than the stock (409, stock unchanged); a two-item order where only the second book is short (409, the first book's stock unchanged); member stats; the top-books report; and borrowing and returning loans. After the extras: `GET /members` paging and invalid bounds, returning the same loan twice (409, stock restored once), and duplicate ISBN and email (409).

**Deliberately skipped:** Neon's CLI onboarding (`neon.ts`, `neon deploy`, MCP setup) is for Neon-hosted functions and configuration. Running it would have added unrelated Node files to a Python repo.

## Spec ambiguities and things I noticed

- **"Don't add new dependencies" conflicts with the required Postgres deployment.** SQLAlchemy can't reach Postgres without a driver, so I added `psycopg[binary]`. It is the only new dependency, and it exists only to meet the deployment requirement.
- **No upper bound on `price_cents` or `stock`.** Postgres `INTEGER` is 32-bit, so values above 2,147,483,647 returned a 500 on Postgres but worked on SQLite. Money, stock and quantity columns are now `BigInteger` on both. I didn't add a schema limit because the spec defines none; values beyond 64 bits (about 9.2 × 10¹⁸) still fail on both databases.
- **Explicit `null` in `PATCH /books/{id}`.** The spec says "any subset" of fields. I treat an omitted field as unchanged but reject `{"title": null}` with a 422, because none of the patchable fields can be empty and silently ignoring a null would hide a client bug.
- **Mixed-case title sorting** differs between SQLite (uppercase first) and Postgres (depends on collation). The spec accepts both; the deployed app uses Postgres ordering.
- **Starter bug:** `tier_at_least` compared with `>` instead of `>=`, so a master member failed the "master or above" check for restricted books. Fixed in its own commit.
- **Late fees use the book's price at return time**, not at borrowing. It's easy to get wrong, so I implemented it exactly as written, and a new test lowers the price mid-loan to prove it.
- **Pending orders hold stock indefinitely.** Stock is reserved at creation and released only by a cancel, so abandoned pending orders tie up inventory. Auto-cancelling pending orders after a timeout would fix it.
- **One `stock` field serves both sales and loans**, so a borrowed copy can't be sold and vice versa. The spec implies a single inventory pool but never says so; a new test pins down this behaviour.
- **Duplicate ISBN and email checks look first, then insert.** Two identical requests at the same moment could both pass the look-up, and the second then hit the database's unique constraint as a 500. It now returns 409 (see Data integrity and concurrency).
- **`GET /members` has no spec.** I mirrored `GET /books` (see Pagination).

## Known gaps and what I'd do with more time

- **No authentication.** Anyone can act as any member, and anyone can add or edit books and create members. The fix is a `get_current_member` dependency that identifies the member from a session or token instead of trusting `member_id` in the request body, plus an admin role for catalog edits. I left it out because it changes the API contract that the spec and tests fix, and it would need new dependencies.
- **Loan-limit and same-book checks can still race.** Two simultaneous borrows by an apprentice can both pass the one-loan limit. A row lock on the member (`SELECT ... FOR UPDATE`) would fix the limit, and a partial unique index on `(member_id, book_id) WHERE returned_at IS NULL` would fix the same-book rule. I left it because SQLite ignores row locks, so no test in this suite could prove the fix works.
- **No concurrency tests.** I'd run part of the suite against a real Postgres (for example a Postgres service in CI) and fire simultaneous requests from threads to prove the stock, status, return and duplicate fixes under real contention.
- **No schema migrations.** `create_all` only creates missing tables, so a column change like the move to `BigInteger` means recreating the database. Alembic would handle it properly, but it's a new dependency.
- **Frontend:** deliberately unchanged apart from the favicon. This is a backend exercise, and changes there would only add regression risk.

## Git history

- The repository's first commit (`4c391e4 Initial commit`) is a bare commit. The starter code and its tests arrived in `4b77a35 Initial Commit + Initial Changes`, together with my first changes, so the starter isn't isolated in its own commit. The test files in that commit are the starter's, unmodified, and the only change under `tests/` since then is the new `test_edge_cases.py`.
- After a first exploratory pass, I rolled back and re-applied the work in phases from a written plan, so each commit covers one logical change.
- Two gaps I left as they are, since the instructions ask for intact history: Phase 1 (schemas, models, books) landed together in `Initial Commit + Initial Changes` through a branch merge, and member stats has no commit of its own because it was built alongside the members service.
- `Artifact Removal` removes AI-generated planning files (the spec analysis and the commit plan) that had been committed by mistake.
- The optional extras landed as one commit per task, each committed only after a full test run.

## AI usage

**Tools**

- **Antigravity IDE:** auditing the starter repo against SPEC.md, listing the spec's traps, drafting a phase-by-phase commit plan, help with the core implementation, and implementing the optional extras from a written plan.
- **Claude:** deployment research (free-tier trade-offs across Render, Neon, Supabase and Vercel), reviewing the Postgres switch, the concurrency rewrite of the orders service, the implementation plan for the optional extras, reviewing Antigravity's output against that plan, and structuring these notes.

**How I used them**

- I carried context between sessions with a written handoff document, so each session started from the spec and the actual state of the repo.
- For the optional extras, I gave Antigravity a written plan with hard rules (no changes to existing tests, no new dependencies, one commit per task) and had it stop after every task until I had run the suite.
- I ran every command myself (`uv run pytest`, the local server, the deploy), and I checked each change against the tests and the live app.

**Where the AI was wrong**

The clearest example: a handoff summary from an earlier session said `autoescape=True` on the search query "prevents SQL injection". It doesn't. SQLAlchemy already sends the search term as a bound parameter, so injection wasn't possible either way; what `autoescape` actually does is stop `%` and `_` from acting as LIKE wildcards. I kept the flag and corrected the reasoning.

Others, from most to least serious:

- **Code that passed every test but was wrong.** The first orders implementation checked stock in Python and then wrote the new value back from Python. Single-threaded tests can't see the problem: two simultaneous orders for the last copy could both succeed, two simultaneous cancels could both restore stock, and a pay could race a cancel. I replaced all of it with conditional updates (see Data integrity and concurrency).
- **A wrong explanation of that bug.** When I asked Antigravity to review its own mistakes, it said the race caused negative stock and broke the all-or-nothing rule. Neither is right. Each request wrote back a value computed from what it had read, so stock ended at 0 with two orders holding one copy: overselling, not negative stock. And a single failed order never left stock half-changed. The rule that actually broke was that an order can't claim more copies than exist.
- **A test that failed for the wrong reason.** A new edge-case test hardcoded the ISBN `1111111111111`, which fails the checksum, so the app correctly rejected it with a 422. Running the suite caught it, and the fix was to let the `make_book` fixture generate valid ISBNs.
- **Drifting from the plan.** Antigravity first wrote every `GET /members` check as a single test function, so a failure wouldn't have shown which case broke. I noticed when the test count rose by one instead of five and had it split them.
- **Incomplete deployment guidance.** The handoff's suggested `db.py` change handled `check_same_thread` but missed `pool_pre_ping`, without which the first request after Neon suspends fails.
- **Loose ends.** A favicon link to a `favicon.png` that didn't exist, and imports placed inside `create_order` for no reason.
- **Unverified claims.** It reported that "all 202 tests should pass" and listed the seeded member IDs without verifying either. I ran the suite and checked the IDs against the live API myself.