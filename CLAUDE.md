# Aria: E-commerce Platform + RAG Chatbot

Full-stack e-commerce app (diving/watersports gear) with a customer storefront,
staff order/refund screens, an admin analytics dashboard, and a RAG chatbot.
ALL DATA IS SYNTHETIC. Never add real personal data to the repo, fixtures, or logs.

## Stack
- Web: Django 6.1 monolith, server-rendered templates + Bootstrap
  (`aria_project/templates/base.html`, per-app `templates/<app>/`). No separate API framework.
- DB: PostgreSQL via `django-environ`; settings read `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
  `DB_HOST`, `DB_PORT` from `aria_project/aria/.env`. ACID matters here.
- RAG chatbot: Claude for generation (not built yet)
- Analytics: Plotly + Apache Spark (not built yet)
- Infra: Docker (single Django container; Postgres runs on the host via
  `host.docker.internal`, there is no DB service in compose), Azure later
- Scale target: 1,000,000 transactions/month (design queries and indexes for this)

## Project layout (`aria_project/`)
- `aria/`: settings, root urls
- `accounts/`: Account (login), Profile, Address models; register/login/logout/profile and
  address-book views; `permissions.py` (role decorators); context processors that put `profile`, `account_id`, `username` in every template
- `products/`: Category, Product, InventoryMovement; browse page, admin dashboard,
  product/category create+edit; `sample_data` management command
- `core/`: home page
- `cart/`: session cart (`cart.py`), cart views, cart-count context processor
- `orders/`: Order, OrderItem, Carrier models; `services.py` (`place_order`, `mark_shipped`),
  `pricing.py` (`quote()`, placeholder tax table), checkout, customer order history, guest order
  link (`links.py`) and lookup, confirmation email (`emails.py`), staff order list/detail/mark shipped
- `payments/`: Payment model, `gateway.py` (`PaymentGateway` protocol + `FakeGateway`),
  `masking.py`, `test_cards.py`
- Payments and tax are TEMPORARY (FakeGateway, placeholder tax table); see docs/follow-ups.md

## Auth (custom, not django.contrib.auth)
- Login checks `Account.password_hash` (Django hashers) and stores `account_id` and
  `username` in the session. Read the current user from `request.session['account_id']`.
- Role lives in `Account.account_type`: `'user'` (customer), `'staff'`, `'admin'`
  (constants `ROLE_CUSTOMER`, `ROLE_STAFF`, `ROLE_ADMIN` in `accounts/models.py`).
- Gate every view with `accounts/permissions.py`: `@login_required` or
  `@role_required(ROLE_STAFF, ROLE_ADMIN)`; get the user with `current_account(request)`.
  Not logged in → login redirect; wrong role → 403; another customer's object → 404
  (filter the lookup by `account=current_account(request)`).
- `/admin/` is the stock Django admin and uses a separate user system; don't rely on it
  for app roles.

## Commands (run from `aria_project/` unless noted)
- Start stack (repo root): `docker compose up --build` (needs Postgres on the host)
- Run locally: `python manage.py runserver`
- Tests: `python manage.py test`  (run before every commit)
  Django 6.1 needs Python >= 3.12. If the host Python is older, run in the Docker image
  (repo root, Git Bash):
  `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/aria_project:/app" -e DB_HOST=host.docker.internal django python manage.py test`
- Migrations: `python manage.py makemigrations` / `python manage.py migrate`
- Sample data: `python manage.py sample_data --password <pw>`
- Lint/format: none configured yet

## Database
- Django models + migrations are the source of truth. Schema changes go through
  migrations only. Never edit the DB by hand.
- `schema.sql`, `sample-data.sql`, `drop-and-recreate-db.ps1` (repo root) are Phase 1
  design artifacts. `schema.sql` does not run as-is and does not match the models; use it
  only as a reference when adding models for orders, payments, refunds, etc.
- Implemented tables: `accounts`, `profiles`, `addresses`, `categories`, `products`,
  `inventory_movements`, `carriers`, `orders`, `order_items`, `payments`.
- Planned (designed in `schema.sql`, no models yet): `refunds`, `accounts_receivable`, `accounts_payable`,
  `policy_documents`.
- Stock changes must write an `InventoryMovement` in the same transaction
  (see `products/views.py` `product_edit_view`).

## Roles and permissions (enforce SERVER-SIDE in every view, never only in the UI)
- Customer (`account_type='user'`): order, request refunds, see ONLY their own history.
  Cannot approve refunds, edit products, or see analytics.
- Staff (`account_type='staff'`): view all orders, approve refunds, use chatbot.
  Payment details are masked. Cannot edit products or see analytics.
- Admin (`account_type='admin'`): analytics, edit products, oversee refunds
  (incl. duplicate-refund flags).
- Guest (not logged in): browse, cart, checkout, and view their own order via the private
  order link or email+order-number lookup. No account pages.
- Shipper: does not sign in, no screen. Do not build one.

## Critical invariants (do not break; add tests when touching these)
1. An order must NEVER show "Confirmed" unless payment succeeded.
   Payment failure or timeout leaves the order unconfirmed.
2. Stock can hit zero before checkout commits. Check and decrement stock
   inside the same transaction that confirms the order (`transaction.atomic()` +
   `select_for_update()`). Handle the failure gracefully (clear message, no charge).
3. Refunds must be idempotent. Disabling the button on first click is only the
   UI layer. The server must also reject duplicates (idempotency key and/or unique
   constraint) and flag duplicate attempts for admin review.
4. Placing an order happens exactly once per checkout (guard against retries
   and double submits).
5. Chatbot cannot execute or cancel anything. It explains and informs only;
   a human confirms any action. It must have no write access to orders/refunds.
6. If the chatbot finds no relevant source, it must REFUSE and offer a human.
   It must not guess. Keep this behavior covered by tests.

## Sensitive data rules
- Payment method: store token + last 4 digits ONLY. Never a full card number,
  never in logs, prompts, fixtures, or chatbot context.
- Fraud/refund-risk score: visible to staff and admin/finance only.
  Never expose to customers or send into customer-facing chatbot answers.
- Retention: customer data = while account active + 2 years;
  order/payment status = 7 years; chat transcripts = 90 days, then anonymized;
  product catalogue is public.
- Customers must never see another customer's data (test this on every new view).

## RAG chatbot
- Sources: ~20 policy documents + order records.
- Order records must be access-scoped to the asking user's role/identity.
- Answers should cite the policy source used.
- Changes to prompts, retrieval, or chunking need a before/after check on a
  fixed set of test questions, including out-of-scope questions that must be refused.

## Scope
- In scope: chatbot, admin analytics dashboard, staff order/refund handling,
  customer payment workflow.
- Out of scope (don't build or suggest): recommendations, tech support,
  predictive analytics/ML, logistics, accounting, crypto, financing,
  international tax, multicurrency, wish lists.
  (The CAD/USD `currency` columns are left over from the Phase 1 design; don't build
  conversion or multicurrency features on them.)
- Deferred: loyalty points, marketing-consent preferences.

## Working agreements
- Before changing code, read the relevant existing modules and follow their patterns.
  Explain the plan first for anything touching orders, payments, refunds, or permissions.
- Never commit secrets (.env, Azure keys, Anthropic API key).
- Git: work on a feature branch, small commits with clear messages, never push to master.
  Open a PR rather than merging directly.
- Don't add dependencies without saying why (`requirements.txt` is UTF-16 encoded;
  keep the encoding when editing it).
