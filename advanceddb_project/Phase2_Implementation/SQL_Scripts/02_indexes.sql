-- Aria Phase 2: indexes.
-- Run while connected to aria_phase2, after 01_tables.sql.
--
-- PostgreSQL already indexes every PRIMARY KEY and UNIQUE constraint. This file adds:
--   1. unique partial indexes that enforce business rules
--   2. an index for every foreign key that is not already the leading column of another index
--      (otherwise deletes/updates on the parent table scan the child table)
--   3. indexes for the filters and sorts used by the app's list pages and the query portfolio
-- The comment on each index names the query it serves. The app's export has several
-- duplicates (e.g. two indexes on order_items.product_id); those are not repeated here.
-- Scale target: 1,000,000 transactions/month.

BEGIN;

-- 1. Business-rule indexes ---------------------------------------------------

-- one default shipping and one default billing address per customer
CREATE UNIQUE INDEX addresses_one_default_per_type
    ON addresses (account_id, address_type) WHERE is_default;

-- business invariant 3: at most one open (REQUESTED/APPROVED) refund per order
CREATE UNIQUE INDEX refunds_one_open_per_order
    ON refunds (order_id) WHERE status IN ('REQUESTED', 'APPROVED');

-- 2 + 3. Foreign keys and access paths ---------------------------------------

-- address book page: a customer's shipping or billing addresses (also covers the account FK)
CREATE INDEX idx_addresses_account_type ON addresses (account_id, address_type);

-- browse page filtered by category; FK to categories
CREATE INDEX idx_products_category ON products (category_id);
-- product search by name (prefix LIKE 'abc%' uses this index)
CREATE INDEX idx_products_name ON products (name varchar_pattern_ops);
-- reorder report (Q04): only the few products at/below their reorder level are indexed
CREATE INDEX idx_products_needs_reorder ON products (category_id)
    WHERE is_active AND stock_quantity <= reorder_level;

-- customer order history, newest first (also covers the account FK)
CREATE INDEX idx_orders_account_created ON orders (account_id, created_at DESC);
-- staff order list filtered by status, newest first
CREATE INDEX idx_orders_status_created ON orders (status, created_at DESC);
-- date-range reports: monthly revenue (Q01), cohorts (Q03), CLV (Q12)
CREATE INDEX idx_orders_created ON orders (created_at);
-- carrier performance (Q06); FK to carriers
CREATE INDEX idx_orders_carrier ON orders (carrier_id) WHERE carrier_id IS NOT NULL;
-- "where is my package" lookup by tracking number
CREATE INDEX idx_orders_tracking ON orders (tracking_number) WHERE tracking_number IS NOT NULL;

-- product sales reports (Q02, Q05); order_id is already covered by
-- the UNIQUE (order_id, product_id) constraint
CREATE INDEX idx_order_items_product ON order_items (product_id);

-- payments for one order; FK to orders
CREATE INDEX idx_payments_order ON payments (order_id);
-- payment failure rate / reconciliation by status over time (Q07)
CREATE INDEX idx_payments_status_created ON payments (status, created_at);

-- stock history for one product, newest first (Q04 last restock); FK to products
CREATE INDEX idx_inv_mov_product_created ON inventory_movements (product_id, created_at DESC);
-- movements caused by one order; FK to orders
CREATE INDEX idx_inv_mov_order ON inventory_movements (reference_order_id)
    WHERE reference_order_id IS NOT NULL;

-- refund history per order is covered by idx_refunds_order_status; FK to payments
CREATE INDEX idx_refunds_order_status ON refunds (order_id, status);
CREATE INDEX idx_refunds_payment ON refunds (payment_id);
-- staff refund queue: open refunds, oldest first
CREATE INDEX idx_refunds_status_requested ON refunds (status, requested_at);
CREATE INDEX idx_refunds_requested_by ON refunds (requested_by) WHERE requested_by IS NOT NULL;
CREATE INDEX idx_refunds_resolved_by ON refunds (resolved_by) WHERE resolved_by IS NOT NULL;

-- admin oversight: unreviewed duplicate attempts
CREATE INDEX idx_dup_refund_unreviewed ON duplicate_refund_attempts (created_at) WHERE reviewed_at IS NULL;
CREATE INDEX idx_dup_refund_order ON duplicate_refund_attempts (order_id);
CREATE INDEX idx_dup_refund_existing ON duplicate_refund_attempts (existing_refund_id)
    WHERE existing_refund_id IS NOT NULL;
CREATE INDEX idx_dup_refund_reviewer ON duplicate_refund_attempts (reviewed_by)
    WHERE reviewed_by IS NOT NULL;

-- receivables aging: open items by due date; FK to orders
CREATE INDEX idx_ar_status_due ON accounts_receivable (status, due_date);
CREATE INDEX idx_ar_order ON accounts_receivable (order_id);

-- payables aging and spend per payee
CREATE INDEX idx_ap_status_due ON accounts_payable (status, due_date);
CREATE INDEX idx_ap_supplier ON accounts_payable (supplier_id) WHERE supplier_id IS NOT NULL;
CREATE INDEX idx_ap_carrier ON accounts_payable (carrier_id) WHERE carrier_id IS NOT NULL;

-- chatbot ingestion: active documents by category
CREATE INDEX idx_policy_documents_active_category ON policy_documents (category) WHERE is_active;

COMMIT;
