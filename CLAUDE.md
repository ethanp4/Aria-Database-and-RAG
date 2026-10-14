# Aria: E-commerce Platform + RAG Chatbot

Full-stack e-commerce app with a customer storefront, staff order/refund screens,
an admin analytics dashboard, and a RAG chatbot. ALL DATA IS SYNTHETIC (Faker).
Never add real personal data to the repo, fixtures, or logs.

## Stack
- DB: PostgreSQL (ACID matters here). Tables: Order, Customer, Product, OrderDetails,
  Payment, Carrier, AccountsReceivable, AccountsPayable
- Backend: Python + FastAPI; RAG pipeline with Claude for generation
- Analytics: Plotly + Apache Spark
- UI prototype: Dash + Plotly (Figma designs); [TODO: confirm real storefront framework]
- Infra: Docker, Azure
- Scale target: 1,000,000 transactions/month (design queries and indexes for this)

## Commands  [TODO: fill in from the repo, keep exact]
- Start stack: `docker compose up`
- Run API: [TODO]
- Tests: [TODO]  (run before every commit)
- Lint/format: [TODO]
- Migrations: [TODO]
- Generate synthetic data: [TODO]

## Roles and permissions (enforce SERVER-SIDE, never only in the UI)
- Customer: order, request refunds, see ONLY their own history.
  Cannot approve refunds, edit products, or see analytics.
- Staff: view all orders, approve refunds, use chatbot.
  Payment details are masked. Cannot edit products or see analytics.
- Admin: analytics, edit products, oversee refunds (incl. duplicate-refund flags).
- Shipper: does not sign in, no screen. Do not build one.

## Critical invariants (do not break; add tests when touching these)
1. An order must NEVER show "Confirmed" unless payment succeeded.
   Payment failure or timeout leaves the order unconfirmed.
2. Stock can hit zero before checkout commits. Check and decrement stock
   inside the same transaction that confirms the order. Handle the failure
   gracefully (clear message, no charge).
3. Refunds must be idempotent. Disabling the button on first click is only the
   UI layer. The API must also reject duplicates (idempotency key and/or unique
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
- Customers must never see another customer's data (test this on every new endpoint).

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
- Deferred: loyalty points, marketing-consent preferences.

## Working agreements
- Before changing code, read the relevant existing modules and follow their patterns.
  Explain the plan first for anything touching orders, payments, refunds, or permissions.
- Schema changes go through migrations only. Never edit the DB by hand.
- Never commit secrets (.env, Azure keys, Anthropic API key).
- Git: work on a feature branch, small commits with clear messages, never push to main.
  Open a PR rather than merging directly.
- Don't add dependencies without saying why.
