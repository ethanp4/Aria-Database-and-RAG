# Aria E-commerce Build: Structure Plan

> **For agentic workers:** This is the master structure plan. It fixes the app layout,
> models, service interfaces, and phase order. Each phase below gets its own detailed
> TDD plan (`docs/superpowers/plans/YYYY-MM-DD-aria-phase-N-<name>.md`) before
> implementation; that plan must use the names and signatures defined here. REQUIRED
> SUB-SKILL for each phase plan: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the Aria storefront, payment workflow, staff order/refund handling,
admin analytics, and a read-only RAG chatbot on the existing Django project, meeting
every invariant in `CLAUDE.md`.

**Architecture:** One Django monolith with server-rendered templates. Each business
area is its own Django app. All state-changing business rules live in
`<app>/services.py` functions (views stay thin and call services). Every invariant is
enforced by a DB constraint where possible and by a service function otherwise. Views
only check permissions and render. Postgres is the only datastore, including the
chatbot's retrieval index.

**Tech Stack:** Django 6.1, PostgreSQL, Bootstrap 5 templates, `anthropic` SDK
(chatbot), Plotly (charts), PySpark (batch analytics aggregates), Faker (bulk
synthetic data).

**Spec:** `CLAUDE.md` (repo root)

## Global Constraints

- All data synthetic; no real personal data in repo, fixtures, logs, prompts.
- Permissions enforced server-side in every view via `accounts/permissions.py`; never only in templates.
- Customers see ONLY their own orders/refunds/chats. Every new view gets a cross-customer test.
- Payment storage: `token` + `last4` only. Never a full card number, anywhere.
- `risk_score` visible to staff and admin only; never in customer templates or chatbot context.
- Retention: customer data = active + 2 years; order/payment status = 7 years; chat transcripts = 90 days then anonymized.
- Schema changes via `makemigrations`/`migrate` only.
- Chatbot has no write path to orders, payments, refunds, products.
- Out of scope: recommendations, tech support, ML, logistics, accounting, crypto, financing, international tax, multicurrency, wish lists. Shipper has no login or screen.
- New dependencies are named and justified in the phase that adds them.
- Scale target: 1,000,000 transactions/month. Every list view is paginated; every filter/sort column used by a list view is indexed.
- Feature branch per phase, small commits, PR into `master`. `python manage.py test` passes before each commit.

## Review Focus

Failure modes no single happy-path test catches. Each has an owning test below.

1. **Double submit / browser retry of checkout** → exactly one order, one charge. Test: `orders/tests/test_place_order.py::test_same_checkout_token_twice_returns_same_order_and_charges_once` (Phase 1).
2. **Two customers buy the last unit at once** → one confirmed, the other gets "out of stock" with the authorization voided. Test: `orders/tests/test_place_order.py::test_concurrent_last_unit_one_wins_loser_voided` (Phase 1, `TransactionTestCase` with two threads).
3. **Gateway capture times out** → order stays `PAYMENT_FAILED`, stock restored, no "Confirmed" shown. Test: `orders/tests/test_place_order.py::test_capture_timeout_leaves_order_unconfirmed_and_restores_stock` (Phase 1).
4. **Customer guesses another order/refund ID in the URL** → 404, not 403 (no existence leak). Tests: `test_customer_cannot_view_other_customers_order` and `test_customer_cannot_refund_other_customers_order` (Phases 1–2).
5. **Chatbot asked about another customer's order or an out-of-scope topic** → refuses and offers a human; never invents. Test: eval questions `cross_customer_order` and `out_of_scope_*` in `chatbot/evals/questions.yaml` (Phase 3).

---

## Target File Structure

```
aria_project/
  aria/settings.py            # + new apps, ARIA_CLAUDE_MODEL, payment gateway setting, env-driven SECRET_KEY/DEBUG (Phase 5)
  accounts/
    models.py                 # Account.account_type += 'staff'; Address (new)
    permissions.py            # NEW: current_account, login_required, role_required, scope helpers
    views.py, urls.py         # + addresses, account page
    tests/                    # convert tests.py to package
  products/                   # existing; views locked to admin (Phase 0); product_details view
  cart/
    cart.py                   # NEW: session-backed Cart
    views.py, urls.py, forms.py, templates/cart/
  orders/                     # NEW app
    models.py                 # Carrier, Order, OrderItem
    services.py               # place_order, mark_shipped
    views.py                  # customer: history, detail
    staff_views.py            # staff: all orders, detail
    templates/orders/, tests/
  payments/                   # NEW app
    models.py                 # Payment
    gateway.py                # PaymentGateway protocol + FakeGateway (synthetic only)
    masking.py                # mask_payment()
    tests/
  refunds/                    # NEW app
    models.py                 # Refund, DuplicateRefundAttempt
    services.py               # request_refund, approve_refund, deny_refund
    views.py, staff_views.py, admin_views.py
    tests/
  chatbot/                    # NEW app
    models.py                 # PolicyDocument, PolicyChunk, ChatSession, ChatMessage
    ingest.py                 # load/chunk policy docs
    retrieval.py              # search_policies, order_context_for
    answer.py                 # answer_question (Claude call)
    views.py, templates/chatbot/
    policies/                 # ~20 synthetic policy .md files
    evals/questions.yaml
    management/commands/      # ingest_policies, run_chatbot_eval
    tests/
  analytics/                  # NEW app (admin only)
    models.py                 # DailySalesSummary, ProductSalesSummary
    jobs/aggregate_sales.py   # PySpark batch job
    queries.py, charts.py, views.py
    tests/
  core/management/commands/apply_retention.py   # Phase 5
  products/management/commands/sample_data.py    # extended with orders etc. (Faker)
```

Roles map to `Account.account_type`: `'user'` = Customer, `'staff'` = Staff, `'admin'` = Admin.

---

## Phase 0: Foundations and permission lockdown

**Branch:** `feature/foundations`. **Depends on:** nothing.

**Files:**
- Create: `accounts/permissions.py`, `accounts/migrations/0004_account_staff_type.py`, `accounts/migrations/0005_address.py`
- Modify: `accounts/models.py`, `products/views.py`, `products/tests.py` (fix `seed_sample_data` → `sample_data`), `products/tests.py::CategoryManagementTests` (log in as admin)
- Test: `accounts/tests/test_permissions.py`, `products/tests.py`

**Interfaces (Produces):**
- `current_account(request) -> Account | None`: reads `request.session['account_id']`; caches it on `request`.
- `login_required(view)`: redirects to `accounts:login` if there is no account.
- `role_required(*roles: str)(view)`: no account → login redirect; wrong role → `HttpResponseForbidden` (403).
- `ROLE_CUSTOMER = 'user'`, `ROLE_STAFF = 'staff'`, `ROLE_ADMIN = 'admin'`
- `Account.account_type` CheckConstraint allows `['user', 'staff', 'admin']`.
- `Address(address_id, account FK, address_type in ['SHIPPING','BILLING'], line1, line2, city, region, postal_code, country in ['CA','US'], is_default)`. Index `(account, address_type)`.

**Key tests:**
- [ ] `test_anonymous_cannot_create_or_edit_product`: POST to `product_create`/`product_edit` → redirect to login, no DB change.
- [ ] `test_customer_and_staff_get_403_on_product_and_category_edit`
- [ ] `test_dashboard_requires_admin` (move existing check onto `role_required(ROLE_ADMIN)`)
- [ ] `test_seed_command_creates_requested_sample_data_idempotently` passes with `call_command('sample_data', ...)`.
- [ ] Register flow: `test_two_users_can_register_before_filling_profile` (fixes the empty unique email bug; make `Profile.email` nullable-unique or create the Profile on the profile form submit instead).

---

## Phase 1: Cart, checkout, orders, payments (invariants 1, 2, 4)

**Branch:** `feature/checkout`. **Depends on:** Phase 0.

**Models:**
- `Carrier(carrier_id, name unique, tracking_url_template)`
- `Order(order_id, account FK RESTRICT, shipping_address FK, billing_address FK, carrier FK null, tracking_number, status, subtotal, shipping_cost, tax_amount, total_amount, checkout_token UUID UNIQUE, confirmed_payment OneToOne(Payment) null, risk_score Decimal(5,2) null, created_at, updated_at, confirmed_at null)`
  - `status in ['PENDING_PAYMENT','PAYMENT_FAILED','OUT_OF_STOCK','CONFIRMED','SHIPPED','DELIVERED','CANCELLED','REFUNDED']`
  - **CheckConstraint `order_confirmed_requires_payment`**: `status IN ('CONFIRMED','SHIPPED','DELIVERED','REFUNDED')` ⇒ `confirmed_payment IS NOT NULL`. This puts invariant 1 in the schema.
  - Indexes: `(account, -created_at)`, `(status, -created_at)`, `created_at`, `tracking_number`.
- `OrderItem(order FK CASCADE, product FK RESTRICT, quantity > 0, unit_price snapshot, line_total)`; index `product`.
- `Payment(payment_id, order FK RESTRICT, amount, method_type in ['CREDIT_CARD','DEBIT_CARD','PAYPAL','GIFT_CARD'], token, last4 CharField(4) null, status in ['AUTHORIZED','CAPTURED','DECLINED','VOIDED','FAILED','REFUNDED'], gateway_ref, created_at)`
  - CheckConstraint: `last4` matches `^[0-9]{4}$` or is null. There is no other card field.
- `InventoryMovement` gains `reference_order FK null` and reason `'RELEASE'` (stock returned after a failed payment).

**Interfaces (Produces):**
- `cart.cart.Cart(request)`: `.add(product_id: int, qty: int)`, `.set(product_id, qty)`, `.remove(product_id)`, `.lines() -> list[CartLine(product, quantity, line_total)]`, `.subtotal() -> Decimal`, `.clear()`. Stored in the session under `'cart'` as `{product_id: qty}`.
- `payments.gateway.PaymentGateway` protocol: `authorize(token: str, amount: Decimal) -> GatewayResult`, `capture(ref: str) -> GatewayResult`, `void(ref: str) -> GatewayResult`. `GatewayResult(ok: bool, ref: str, error: str | None)`. Raises `GatewayTimeout`. `FakeGateway` decides outcomes by token (`tok_ok`, `tok_decline`, `tok_timeout_capture`). The class is picked by `settings.ARIA_PAYMENT_GATEWAY`.
- `payments.masking.mask_payment(payment) -> str` → `"Visa •••• 4242"`-style; `"•••• ----"` when `last4` is null.
- `orders.services.place_order(account: Account, cart_lines: list[CartLine], shipping_address_id: int, billing_address_id: int, payment_token: str, last4: str | None, method_type: str, checkout_token: UUID) -> Order`
  - Raises `OutOfStock(product_ids: list[int])` and `PaymentDeclined(reason: str)`.
- `orders.services.mark_shipped(staff: Account, order_id: int, carrier_id: int, tracking_number: str) -> Order`

**`place_order` algorithm (this decides invariants 1, 2 and 4):**
1. `Order.objects.get_or_create(checkout_token=..., defaults={status: PENDING_PAYMENT, ...})`. **Only the request that created the row continues.** If `created` is False, return the existing order unchanged, whatever its status (a still-`PENDING_PAYMENT` order renders as "processing"). That way a concurrent double submit can never authorize twice. The checkout page renders a fresh `uuid4` in a hidden field, and the submit button is disabled with JS on click (UI layer only).
2. `gateway.authorize(token, total)`. On decline: mark the order `PAYMENT_FAILED`, raise `PaymentDeclined`. No stock is touched.
3. `with transaction.atomic()`: `Product.objects.select_for_update().filter(pk__in=ids).order_by('pk')` (fixed lock order prevents deadlocks).
   - If any `stock_quantity < qty`: roll back, `gateway.void(ref)`, mark the order `OUT_OF_STOCK`, raise `OutOfStock`. The customer is never charged because the payment was only authorized, never captured.
   - Otherwise: decrement stock, write `InventoryMovement(SALE, reference_order)`, `gateway.capture(ref)`. If capture fails or times out, raise inside the atomic block, so the stock decrement rolls back.
   - On capture success: create `Payment(CAPTURED)`, set `order.confirmed_payment`, `status=CONFIRMED`, `confirmed_at`.
4. Outside the atomic block: on capture failure, mark the order `PAYMENT_FAILED`, `Payment(FAILED)`, `gateway.void(ref)`.

**Views:**
- `cart:detail`, `cart:add`, `cart:update`, `cart:checkout` (`login_required`).
- `orders:history` (paginated, own orders only), `orders:detail` (`get_object_or_404(Order, pk=..., account=current_account(request))`).
- `orders:staff_list` (paginated, filter by status/date) and `orders:staff_detail` (`role_required(STAFF, ADMIN)`). Payments are shown only through `mask_payment`.
- `products:detail`, using the existing `product_details.html`.

**Key tests (`orders/tests/test_place_order.py`, `TransactionTestCase` where noted):**
- [ ] `test_successful_checkout_confirms_order_decrements_stock_and_logs_sale`
- [ ] `test_declined_payment_leaves_order_payment_failed_and_stock_untouched`
- [ ] `test_capture_timeout_leaves_order_unconfirmed_and_restores_stock`
- [ ] `test_out_of_stock_voids_authorization_and_shows_clear_message`
- [ ] `test_same_checkout_token_twice_returns_same_order_and_charges_once` (FakeGateway records calls; assert one capture)
- [ ] `test_concurrent_last_unit_one_wins_loser_voided` (TransactionTestCase, 2 threads)
- [ ] `test_concurrent_double_submit_same_token_authorizes_once` (TransactionTestCase, 2 threads, same `checkout_token`)
- [ ] `test_db_rejects_confirmed_order_without_payment` (raw `.update(status='CONFIRMED')` → `IntegrityError`)
- [ ] `test_payment_rejects_non_digit_last4`
- [ ] `test_customer_cannot_view_other_customers_order` → 404
- [ ] `test_staff_order_detail_shows_masked_payment_only` (response does not contain the token)
- [ ] `test_customer_order_pages_never_render_risk_score`

---

## Phase 2: Refunds, staff handling, admin oversight (invariant 3)

**Branch:** `feature/refunds`. **Depends on:** Phase 1.

**Models:**
- `Refund(refund_id, order FK RESTRICT, payment FK RESTRICT, amount > 0, reason, status in ['REQUESTED','APPROVED','DENIED','COMPLETED'], idempotency_key UUID UNIQUE, requested_by FK Account, resolved_by FK Account null, risk_score Decimal null, requested_at, resolved_at)`
  - **UniqueConstraint `one_open_refund_per_order`**: `fields=['order'], condition=Q(status__in=['REQUESTED','APPROVED'])`.
  - Index `(status, requested_at)`.
- `DuplicateRefundAttempt(attempt_id, order FK, account FK, idempotency_key, existing_refund FK null, reason in ['SAME_KEY','OPEN_REFUND_EXISTS','ALREADY_REFUNDED','APPROVE_TWICE'], created_at, reviewed_by FK null, reviewed_at null)`

**Interfaces (Produces):**
- `refunds.services.request_refund(account: Account, order_id: int, amount: Decimal, reason: str, idempotency_key: UUID) -> Refund`
  - Order must belong to the account (else `Order.DoesNotExist` → 404) and be `CONFIRMED`/`SHIPPED`/`DELIVERED`. The total of completed refunds plus this amount must be ≤ `order.total_amount`.
  - A repeated `idempotency_key` returns the existing Refund **and** records a `DuplicateRefundAttempt(SAME_KEY)`.
  - An `IntegrityError` on `one_open_refund_per_order` raises `DuplicateRefund` and records `DuplicateRefundAttempt(OPEN_REFUND_EXISTS)`. Write the attempt in a separate transaction so the rollback doesn't discard the flag.
- `refunds.services.approve_refund(staff: Account, refund_id: int) -> Refund`: `select_for_update`; only `REQUESTED → APPROVED → COMPLETED` (calls `gateway` refund via `PaymentGateway.refund(ref, amount)`, added in this phase). A second call records `APPROVE_TWICE` and returns without paying out again. Marks the order `REFUNDED` when it is fully refunded and writes `InventoryMovement(REFUND)` if goods are returned.
- `refunds.services.deny_refund(staff: Account, refund_id: int, note: str) -> Refund`
- `refunds.services.compute_risk_score(refund: Refund) -> Decimal`: deterministic rules (count of prior refunds, refund/order value ratio, account age). No ML (out of scope).

**Views:**
- Customer: `refunds:request` (form with hidden `idempotency_key`, `login_required`), with their refunds listed on the order detail page.
- Staff: `refunds:queue` (paginated, REQUESTED first, shows `risk_score`), `refunds:approve`, `refunds:deny` (POST only, `role_required(STAFF, ADMIN)`).
- Admin: `refunds:oversight`: all refunds and unreviewed `DuplicateRefundAttempt` flags, "mark reviewed" action (`role_required(ADMIN)`).

**Key tests:**
- [ ] `test_same_idempotency_key_returns_existing_refund_and_flags_duplicate`
- [ ] `test_second_open_refund_for_order_rejected_and_flagged`
- [ ] `test_approve_twice_pays_out_once_and_flags`
- [ ] `test_refund_cannot_exceed_order_total`
- [ ] `test_customer_cannot_refund_other_customers_order` → 404
- [ ] `test_customer_cannot_approve_refund` → 403
- [ ] `test_staff_cannot_open_admin_oversight` → 403
- [ ] `test_risk_score_absent_from_customer_refund_pages`

---

## Phase 3: RAG chatbot (invariants 5, 6)

**Branch:** `feature/chatbot`. **Depends on:** Phase 2 (order/refund data to explain).
**New dependency:** `anthropic`, for the Claude API, the generation model named in CLAUDE.md. Retrieval uses Postgres full-text search (`django.contrib.postgres.search`), which needs no new dependency. With ~20 documents this is enough. Move to pgvector only if the eval set shows retrieval misses.

**Models:**
- `PolicyDocument(document_id, title, category, source_path, version, is_active, updated_at)`
- `PolicyChunk(chunk_id, document FK CASCADE, ordinal, heading, text, search_vector SearchVectorField)` + `GinIndex(search_vector)`
- `ChatSession(session_id, account FK null, created_at, anonymized_at null)`
- `ChatMessage(message_id, session FK CASCADE, role in ['user','assistant'], text, cited_chunks M2M PolicyChunk, refused bool, created_at)`; index `created_at`.

**Interfaces (Produces):**
- `chatbot.ingest.ingest_policies(directory: Path) -> int`: splits markdown on headings (~300–800 words per chunk) and upserts by `(source_path, ordinal)`. Command: `python manage.py ingest_policies`.
- `chatbot.retrieval.search_policies(question: str, limit: int = 5) -> list[ScoredChunk]` (`SearchRank`, active documents only).
- `chatbot.retrieval.order_context_for(account: Account, question: str) -> list[dict]`
  - Customers: only their own orders.
  - Staff/admin: an order referenced by ID.
  - Returns only `order_id, status, created_at, total_amount, carrier name, tracking_number, refund statuses`. **Never** `token`, `last4`, `risk_score`.
- `chatbot.answer.answer_question(account: Account, session: ChatSession, question: str) -> ChatAnswer(text: str, citations: list[PolicyChunk], refused: bool)`
  - If no chunk scores ≥ `settings.ARIA_RAG_MIN_RANK` **and** there is no relevant order context, refuse **without calling Claude**: "I don't have a source for that. Would you like me to connect you with a staff member?"
  - Otherwise call Claude (`settings.ARIA_CLAUDE_MODEL`, default `claude-sonnet-5-5`). The system prompt says: answer only from the provided sources, cite `[title]`, refuse when the sources don't cover the question, never claim to perform actions.
  - The model output is post-checked: an answer with no citation is converted to the refusal.
- The `chatbot` package imports no `services` module from orders, refunds, payments or products. A test enforces this.

**Views:** `chatbot:chat` (`login_required`, all roles). "Talk to a human" shows the support contact; it does not create tickets.

**Evals:**
- `chatbot/evals/questions.yaml`: ≥30 questions with `expect: answer|refuse` and `expect_source`.
  - Include: shipping, returns windows, refund timing, the user's own order status, `cross_customer_order`, `out_of_scope_crypto`, `out_of_scope_recommendation`, `action_request_cancel_my_order` (must explain how, not do it), and a prompt injection inside the question.
- `python manage.py run_chatbot_eval [--baseline path]` prints a pass/fail table and a diff vs. the baseline. Required before/after any change to prompts, retrieval or chunking.

**Key tests (Claude client mocked):**
- [ ] `test_no_relevant_source_refuses_without_calling_claude`
- [ ] `test_answer_without_citation_converted_to_refusal`
- [ ] `test_order_context_scoped_to_customer` / `test_order_context_never_contains_token_last4_or_risk_score`
- [ ] `test_chat_request_performs_no_writes_outside_chat_tables` (`connection.execute_wrapper` fails on INSERT/UPDATE/DELETE to any table except `chatbot_chatsession`/`chatbot_chatmessage`)
- [ ] `test_chatbot_package_does_not_import_write_services`
- [ ] `test_customer_cannot_read_other_customers_chat_session` → 404

---

## Phase 4: Admin analytics dashboard

**Branch:** `feature/analytics`. **Depends on:** Phase 1 (orders), Phase 2 (refunds).
**New dependencies:**
- `plotly`: the chart library named in CLAUDE.md. Renders figures to HTML divs server-side.
- `pyspark`: named in CLAUDE.md. Runs batch aggregation over 1M+ monthly transactions outside the request path.

**Models:** `DailySalesSummary(day, orders_count, gross_revenue, refunds_count, refund_amount, avg_order_value)` unique `day`; `ProductSalesSummary(day, product FK, units_sold, revenue)` unique `(day, product)`.

**Interfaces (Produces):**
- `analytics/jobs/aggregate_sales.py`: `spark-submit` job. Reads `orders`, `order_items`, `refunds` over JDBC for a date range and upserts the summary tables. Command wrapper: `python manage.py aggregate_sales --since YYYY-MM-DD`. It also has an ORM fallback (`--engine orm`) for dev and tests.
- `analytics.queries`: `sales_by_day(start, end) -> list[dict]`, `top_products(start, end, limit=10)`, `refund_rate(start, end)`, `order_status_breakdown(start, end)`. These read **only** summary tables or indexed counts; there is never a full scan per request.
- `analytics.charts`: one function per chart → `str` (Plotly HTML div). Follow the dataviz skill for palette and form.
- `analytics:dashboard` (`role_required(ADMIN)`) replaces/extends the current `products:dashboard` stats. The product-management lists move to a paginated `products:manage` page.

**Key tests:**
- [ ] `test_aggregate_orm_engine_matches_hand_computed_totals`
- [ ] `test_dashboard_admin_only` (customer 403, staff 403)
- [ ] `test_dashboard_query_count_constant` (`assertNumQueries`, independent of order volume)

---

## Phase 5: Retention, scale, deploy-readiness

**Branch:** `feature/ops`. **Depends on:** Phases 1–3.
**New dependency:** `Faker`, for generating realistic synthetic volume (1M orders) for load and index checks.

- `core/management/commands/apply_retention.py` (run daily via cron or an Azure scheduled job):
  - Anonymize `ChatMessage.text` and null `ChatSession.account` after 90 days.
  - Anonymize `Profile`/`Address` PII for accounts inactive > 2 years. Orders keep `account` FK and amounts.
  - Never delete `Order`/`Payment` rows younger than 7 years.
  - Tests use frozen dates at each boundary (89/90/91 days, etc.).
- `sample_data --orders N`: Faker-generated customers, addresses, orders, payments (token `tok_fake_*`, Faker last4), refunds. Used to `EXPLAIN ANALYZE` every list view at 1M orders; add missing indexes via migration.
- Settings: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` from env. Gunicorn in the Dockerfile; `runserver` only for dev. Add a `postgres` service to `docker-compose.yml` for local dev.
- Structured logging that never logs request bodies on checkout/refund views, plus a test that asserts no token or last4 appears in log output during checkout.

---

## Phase order and dependencies

```
Phase 0 Foundations ──► Phase 1 Checkout ──► Phase 2 Refunds ──► Phase 3 Chatbot
                                   │                 │
                                   └──────► Phase 4 Analytics ◄┘
Phase 5 Ops: after 1–3 (retention needs chats); Faker volume data can start after Phase 1.
```

Phases 3 and 4 are independent of each other and can run in parallel on separate branches once Phase 2 merges.
