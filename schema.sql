-- =====================================================================
-- ARIA Database Schema (PostgreSQL)
-- DBAD 4000 Advanced Database - Aria Transactional Analysis & Data Integrity
-- =====================================================================

-- Run this in a database called aria with a user named aria (create_db_and_user.sql)

-- =====================================================================
-- CUSTOMERS
-- =====================================================================
CREATE TABLE IF NOT EXISTS customers (
    customer_id     BIGSERIAL PRIMARY KEY,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone           VARCHAR(20),
    password_hash   VARCHAR(255) NOT NULL,          -- registered accounts only
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Frequent lookups: login by email, staff search by name
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email ON customers (email);
CREATE INDEX IF NOT EXISTS idx_customers_last_name ON customers (last_name);

-- =====================================================================
-- ADDRESSES  (customer can have multiple: billing / shipping)
-- =====================================================================
CREATE TABLE IF NOT EXISTS addresses (
    address_id      BIGSERIAL PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    address_type    VARCHAR(10) NOT NULL CHECK (address_type IN ('SHIPPING', 'BILLING')),
    line1           VARCHAR(255) NOT NULL,
    line2           VARCHAR(255),
    city            VARCHAR(100) NOT NULL,
    region          VARCHAR(100) NOT NULL,           -- state/province
    postal_code     VARCHAR(20) NOT NULL,
    country         VARCHAR(2) NOT NULL CHECK (country IN ('CA', 'US')),
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Frequent lookup: "give me this customer's addresses"
CREATE INDEX IF NOT EXISTS idx_addresses_customer_id ON addresses (customer_id);
CREATE INDEX IF NOT EXISTS idx_addresses_customer_type ON addresses (customer_id, address_type);

-- =====================================================================
-- PRODUCTS  (diving/watersports gear)
-- =====================================================================
CREATE TABLE IF NOT EXISTS products (
    product_id      BIGSERIAL PRIMARY KEY,
    sku             VARCHAR(50) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    category        VARCHAR(100),
    unit_price      NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    currency        VARCHAR(3) NOT NULL DEFAULT 'CAD' CHECK (currency IN ('CAD', 'USD')),
    stock_quantity  INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    reorder_level   INTEGER NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- High-volume read path: product catalog browsing / lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products (sku);
CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);
CREATE INDEX IF NOT EXISTS idx_products_name ON products (name);
CREATE INDEX IF NOT EXISTS idx_products_active ON products (is_active) WHERE is_active = TRUE;

-- =====================================================================
-- INVENTORY MOVEMENTS  (audit trail for stock changes)
-- =====================================================================
CREATE TABLE IF NOT EXISTS inventory_movements (
    movement_id     BIGSERIAL PRIMARY KEY,
    product_id      BIGINT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    change_qty      INTEGER NOT NULL,                -- negative = stock out, positive = stock in
    reason          VARCHAR(20) NOT NULL CHECK (reason IN ('SALE', 'RESTOCK', 'REFUND', 'ADJUSTMENT')),
    reference_order_id BIGINT,                       -- nullable FK to orders, linked via ALTER after orders is created
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inventory_movements_product_id ON inventory_movements (product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_created_at ON inventory_movements (created_at);

-- =====================================================================
-- CARRIERS
-- =====================================================================
CREATE TABLE IF NOT EXISTS carriers (
    carrier_id      BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    tracking_url_template VARCHAR(255)                -- e.g. https://carrier.com/track/{tracking_number}
);

-- =====================================================================
-- ORDERS  (single flat table, one order = one shipment)
-- =====================================================================
CREATE TABLE IF NOT EXISTS orders (
    order_id        BIGSERIAL PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES customers(customer_id) ON DELETE RESTRICT,
    shipping_address_id BIGINT NOT NULL REFERENCES addresses(address_id) ON DELETE RESTRICT,
    billing_address_id  BIGINT NOT NULL REFERENCES addresses(address_id) ON DELETE RESTRICT,
    carrier_id      BIGINT REFERENCES carriers(carrier_id) ON DELETE SET NULL,
    tracking_number VARCHAR(100),
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'PAID', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED')),
    currency        VARCHAR(3) NOT NULL CHECK (currency IN ('CAD', 'USD')),
    subtotal        NUMERIC(10, 2) NOT NULL CHECK (subtotal >= 0),
    shipping_cost   NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (shipping_cost >= 0),
    tax_amount      NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    total_amount    NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0),
    order_date      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Frequent access patterns: customer order history, staff status queues,
-- date-range reporting, tracking lookups
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders (order_date);
CREATE INDEX IF NOT EXISTS idx_orders_tracking_number ON orders (tracking_number);
-- Composite index for the very common "this customer's orders, newest first"
CREATE INDEX IF NOT EXISTS idx_orders_customer_date ON orders (customer_id, order_date DESC);

-- Now that orders exists, link inventory_movements to it (idempotent:
-- only add the constraint if it doesn't already exist).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_inventory_movements_order'
    ) THEN
        ALTER TABLE inventory_movements
            ADD CONSTRAINT fk_inventory_movements_order
            FOREIGN KEY (reference_order_id) REFERENCES orders(order_id) ON DELETE SET NULL;
    END IF;
END $$;

-- =====================================================================
-- ORDER_ITEMS  (line items)
-- =====================================================================
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id   BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id      BIGINT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),  -- price at time of sale (snapshot)
    line_total      NUMERIC(10, 2) NOT NULL CHECK (line_total >= 0)
);

-- Frequent access: "items for this order" and "sales history for this product"
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items (product_id);

-- =====================================================================
-- PAYMENTS
-- =====================================================================
CREATE TABLE IF NOT EXISTS payments (
    payment_id      BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,
    amount          NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    currency        VARCHAR(3) NOT NULL CHECK (currency IN ('CAD', 'USD')),
    payment_method  VARCHAR(20) NOT NULL CHECK (payment_method IN ('CREDIT_CARD', 'DEBIT_CARD', 'PAYPAL', 'GIFT_CARD')),
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'APPROVED', 'DECLINED', 'REFUNDED')),
    transaction_ref VARCHAR(100),                     -- external payment processor reference
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Frequent access: "payments for this order", reconciliation by status/date
CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments (order_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);
CREATE INDEX IF NOT EXISTS idx_payments_processed_at ON payments (processed_at);

-- =====================================================================
-- REFUNDS
-- =====================================================================
CREATE TABLE IF NOT EXISTS refunds (
    refund_id       BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,
    payment_id      BIGINT NOT NULL REFERENCES payments(payment_id) ON DELETE RESTRICT,
    amount          NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    currency        VARCHAR(3) NOT NULL CHECK (currency IN ('CAD', 'USD')),
    reason          VARCHAR(255),
    status          VARCHAR(20) NOT NULL DEFAULT 'REQUESTED'
                        CHECK (status IN ('REQUESTED', 'APPROVED', 'DENIED', 'COMPLETED')),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

-- Frequent access: support staff looking up refund status/history per order
CREATE INDEX IF NOT EXISTS idx_refunds_order_id ON refunds (order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_payment_id ON refunds (payment_id);
CREATE INDEX IF NOT EXISTS idx_refunds_status ON refunds (status);

-- =====================================================================
-- ACCOUNTS RECEIVABLE  (simple status tracking: money owed TO Aria)
-- =====================================================================
CREATE TABLE IF NOT EXISTS accounts_receivable (
    ar_id           BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,
    amount_due      NUMERIC(10, 2) NOT NULL CHECK (amount_due >= 0),
    currency        VARCHAR(3) NOT NULL CHECK (currency IN ('CAD', 'USD')),
    due_date        DATE NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                        CHECK (status IN ('OPEN', 'PAID', 'OVERDUE', 'WRITTEN_OFF')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ar_order_id ON accounts_receivable (order_id);
CREATE INDEX IF NOT EXISTS idx_ar_status ON accounts_receivable (status);
CREATE INDEX IF NOT EXISTS idx_ar_due_date ON accounts_receivable (due_date);

-- =====================================================================
-- ACCOUNTS PAYABLE  (simple status tracking: money Aria owes suppliers/carriers)
-- =====================================================================
CREATE TABLE IF NOT EXISTS accounts_payable (
    ap_id           BIGSERIAL PRIMARY KEY,
    carrier_id      BIGINT REFERENCES carriers(carrier_id) ON DELETE SET NULL,
    vendor_name     VARCHAR(255) NOT NULL,
    amount_due      NUMERIC(10, 2) NOT NULL CHECK (amount_due >= 0),
    currency        VARCHAR(3) NOT NULL CHECK (currency IN ('CAD', 'USD')),
    due_date        DATE NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                        CHECK (status IN ('OPEN', 'PAID', 'OVERDUE')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ap_status ON accounts_payable (status);
CREATE INDEX IF NOT EXISTS idx_ap_due_date ON accounts_payable (due_date);

-- =====================================================================
-- POLICY DOCUMENTS  (metadata for the 20 docs backing the RAG chatbot;
-- actual document content/embeddings live in a vector store, not here)
-- =====================================================================
CREATE TABLE IF NOT EXISTS policy_documents (
    document_id     BIGSERIAL PRIMARY KEY,
    title           VARCHAR(255) NOT NULL,
    category        VARCHAR(100),                    -- e.g. 'Shipping', 'Refunds', 'HR'
    file_path       VARCHAR(500) NOT NULL,            -- location of source file for RAG ingestion
    version         VARCHAR(20) NOT NULL DEFAULT '1.0',
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_policy_documents_category ON policy_documents (category);
CREATE INDEX IF NOT EXISTS idx_policy_documents_active ON policy_documents (is_active) WHERE is_active = TRUE;
