# Schema reconciliation: Phase 1 design vs. app vs. Phase 2

There are three versions of the Aria schema:

| Source | What it is | Status |
|---|---|---|
| `schema.sql` (repo root) | Phase 1 design, written from the EERD | Design artifact. It doesn't run as-is and predates the app. |
| `reference/app_schema_export.sql` | `pg_dump` of the Django app's live `aria` database | Owned by Django migrations. Has 10 tables. |
| `01_tables.sql` + `02_indexes.sql` | **Phase 2 implementation** (`aria_phase2` database) | Has 16 tables and is the version this deliverable runs. |

**Rule used to reconcile them:** the app's live schema wins wherever it already implements an entity, because it has been built and tested against real checkout flows. The Phase 1 design fills in the entities the app doesn't have yet. On top of both, Phase 2 adds constraints that move rules from Python code into the database.

## 1. Tables

| Table | Phase 1 `schema.sql` | App (live) | Phase 2 | Notes |
|---|---|---|---|---|
| accounts | yes | yes | yes | App version kept. The `staff` role was added after Phase 1. |
| profiles | yes | yes | yes | App version kept. |
| addresses | yes (`customer_id`) | yes (`account_id`) | yes | Renamed to match the app. `is_default` was added. |
| categories | yes | yes | yes | |
| products | yes | yes | yes | Added checks on price, reorder level and currency. |
| carriers | yes | yes | yes | Added a check that the URL template contains `{tracking_number}`. |
| orders | yes | yes | yes | App version, plus `shipped_at` / `delivered_at` (section 3). |
| order_items | yes | yes | yes | Added `line_total = quantity * unit_price` and one line per product. |
| payments | yes | yes | yes | App version. It stores only the token and last 4 digits. |
| inventory_movements | yes | yes | yes | Added sign-per-reason and "a sale has an order" checks. |
| **suppliers** | **no** (only in the EERD and README) | no | **new** | Resolves the suppliers mismatch (section 2). |
| refunds | yes | no (planned) | **new** | Phase 1 design plus the idempotency key, requester/resolver and risk score. |
| duplicate_refund_attempts | no | no (planned) | **new** | Admin review queue for blocked duplicate refunds (business invariant 3). |
| accounts_receivable | yes | no | **new** | Linked to the payment being settled. |
| accounts_payable | yes | no | **new** | Implements the Payee subtype (section 2). |
| policy_documents | yes | no (planned) | **new** | Category list fixed. Unique on `(file_path, version)`. |

## 2. The suppliers mismatch

**What was wrong:**
- The Phase 1 README (design decision 10) and the EERD describe a **disjoint Payee subtype**: a payee is either a Supplier or a Carrier, never both.
- `schema.sql` never created a `suppliers` table. `accounts_payable` used an optional `carrier_id` plus a free-text `vendor_name`, so nothing enforced the subtype and supplier bills had no foreign key.
- The app has neither table, because accounting is out of scope for the app.

**Resolution in Phase 2:**
- Add a `suppliers` table (25 synthetic vendors).
- Implement Payee as an **exclusive arc** on `accounts_payable`: `supplier_id` and `carrier_id` are both nullable foreign keys, and
  `CONSTRAINT ap_one_payee CHECK (num_nonnulls(supplier_id, carrier_id) = 1)` guarantees that exactly one is set. That *is* the disjoint rule, enforced by the database.
- `vendor_name` is dropped. The payee's name now comes from the referenced row, so it can't drift.
- Why not a separate `payees` supertype table? Carriers already exist in the app with their own id. A supertype would mean re-keying `carriers` in the app. With only two subtypes, the exclusive arc gives the same guarantee with simpler joins.

## 3. Column-level differences (Phase 1 → app/Phase 2)

| Phase 1 | App / Phase 2 | Why |
|---|---|---|
| `orders.customer_id` NOT NULL | `orders.account_id` NULL allowed | Guest checkout. `orders_has_owner` requires an account or a contact email. |
| `orders.order_date` | `orders.created_at` (+ `confirmed_at`) | The confirmation time is separate from when the order was placed. |
| `orders.shipping_address_id` FK | `ship_*` / `bill_*` snapshot columns | An order must keep the address it shipped to, even if the customer later edits or deletes it. |
| `payments.processed_at` | `payments.created_at` | Naming consistency. |
| `refunds.currency`, `ar/ap.currency` | dropped | Orders are single-currency; multicurrency is out of scope. |
| (none) | `orders.checkout_token UUID UNIQUE` | One order per checkout attempt, so a double submit can't create two orders (invariant 4). |
| (none) | `orders.confirmed_payment_id` | Lets a CHECK prove a confirmed order has a payment (invariant 1). |
| (none) | `orders.shipped_at`, `delivered_at` | **Phase 2 addition.** Needed for carrier delivery-time reporting (Q06). Should become an app migration. |
| (none) | `refunds.idempotency_key UUID UNIQUE` | A retried refund request can't pay out twice (invariant 3). |

## 4. Constraints added beyond the app

The app enforces these rules in Python (Django forms and services). In Phase 2 the database enforces them too, so a bad row can't be written by any client:

- `orders_total_adds_up`: total = subtotal + shipping + tax.
- `orders_confirmed_requires_payment`: now also requires `confirmed_at`.
- `orders_shipped_has_tracking`, `orders_delivered_has_date`, `orders_timeline_ordered`: shipping events happen in order.
- `orders_risk_score_range`, `refunds_risk_score_range`: 0-100.
- `order_items_line_total`, `order_items_one_line_per_product`.
- `payments_card_fields`: cards carry last4 and brand; PayPal and gift cards carry neither (the disjoint payment types from design decision 9).
- `inv_mov_sign_matches_reason`: a SALE removes stock, RESTOCK/REFUND add it, ADJUSTMENT can go either way but is never 0.
- `inv_mov_sale_has_order`: sales and refund returns reference their order.
- `products_price_nonnegative`, `products_reorder_nonnegative`, `products_currency_valid`.
- `refunds_one_open_per_order` (unique partial index) and `refunds_resolution_consistent`.
- Foreign keys declare `ON DELETE` behaviour in the database. Django's own FKs are `NO ACTION` and it emulates CASCADE/RESTRICT/SET NULL in Python.

## 5. Indexes

**Removed (duplicates in the app export):**

| Duplicate in the app | Already covered by |
|---|---|
| `idx_order_items_product` + `order_items_product_id_…` | one index on `order_items(product_id)` |
| `idx_payments_order` + `payments_order_id_…` | one index on `payments(order_id)` |
| `idx_products_category` + `products_category_id_…` | one index on `products(category_id)` |
| `idx_products_sku` + `products_sku_…_like` | the UNIQUE constraint's index |
| `accounts_username_key` + `unique_username` | one constraint on `accounts(username)` |
| `addresses_account_id_…` | `idx_addresses_account_type (account_id, address_type)` (same leading column) |
| `orders_account_id_…` | `idx_orders_account_created` (same leading column) |
| `order_items_order_id_…` | the UNIQUE `(order_id, product_id)` |

**Added:**
- `idx_inv_mov_product_created (product_id, created_at DESC)`: a product's stock history and last restock (Q04).
- `idx_products_needs_reorder`: a partial index over only the products at or below their reorder level (Q04).
- `idx_orders_carrier`: carrier performance (Q06) and the carrier FK.
- Indexes for every foreign key on the new tables, plus queue/aging indexes: `idx_refunds_status_requested`, `idx_ar_status_due`, `idx_ap_status_due`, `idx_dup_refund_unreviewed`.

`02_indexes.sql` comments each index with the query it serves.

## 6. Follow-ups for the app (not done here)

These should become Django migrations on the app side:
- `orders.shipped_at` / `delivered_at`
- the extra CHECK constraints in section 4
- dropping the duplicate indexes in section 5
- the refunds / duplicate_refund_attempts models (app Phase 2)
