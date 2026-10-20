-- Q09  Triggers: take stock when an order is confirmed
-- Business question: How do we guarantee that confirming an order always removes the stock and
--   logs it, and that we never confirm an order we can't fill, even if two customers buy the
--   last unit at the same moment?
-- Techniques: PL/pgSQL trigger functions; an AFTER UPDATE OF status trigger with a WHEN
--   condition; SELECT ... FOR UPDATE row locks taken in a fixed order (prevents deadlocks);
--   RAISE EXCEPTION to abort the whole transaction; a BEFORE UPDATE trigger maintaining updated_at.
--
-- Business invariant 2: stock is checked and decremented inside the same transaction that
-- confirms the order. A second buyer waits on the row lock, then sees the reduced stock.

-- keeps orders.updated_at current on every change
CREATE OR REPLACE FUNCTION fn_orders_touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_orders_touch_updated_at ON orders;
CREATE TRIGGER trg_orders_touch_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION fn_orders_touch_updated_at();

-- PENDING_PAYMENT -> CONFIRMED: lock each product, check stock, decrement, log a SALE movement
CREATE OR REPLACE FUNCTION fn_orders_take_stock() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    line record;
BEGIN
    FOR line IN
        SELECT oi.product_id, oi.quantity, p.sku, p.stock_quantity, p.is_active
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        WHERE oi.order_id = NEW.order_id
        ORDER BY oi.product_id                      -- same lock order in every transaction
        FOR UPDATE OF p
    LOOP
        IF NOT line.is_active OR line.stock_quantity < line.quantity THEN
            RAISE EXCEPTION 'Out of stock: % (in stock %, ordered %)',
                            line.sku, line.stock_quantity, line.quantity
                USING ERRCODE = 'check_violation',
                      HINT = 'Do not confirm the order; void the payment authorization.';
        END IF;
        UPDATE products
           SET stock_quantity = stock_quantity - line.quantity,
               updated_at = now()
         WHERE product_id = line.product_id;
        INSERT INTO inventory_movements (product_id, change_qty, reason, reference_order_id)
        VALUES (line.product_id, -line.quantity, 'SALE', NEW.order_id);
    END LOOP;
    RETURN NULL;                                     -- AFTER trigger: return value ignored
END $$;

DROP TRIGGER IF EXISTS trg_orders_take_stock ON orders;
CREATE TRIGGER trg_orders_take_stock
    AFTER UPDATE OF status ON orders
    FOR EACH ROW
    WHEN (OLD.status = 'PENDING_PAYMENT' AND NEW.status = 'CONFIRMED')
    EXECUTE FUNCTION fn_orders_take_stock();

-- ---------------------------------------------------------------------------
-- Demo. Everything below runs in one transaction that is ROLLED BACK at the end,
-- so the seed data stays unchanged and the demo can be re-run.
-- Order ids 900001+ are reserved for demos.
-- ---------------------------------------------------------------------------
BEGIN;

-- stock before: MASK-001
SELECT sku, stock_quantity FROM products WHERE sku = 'MASK-001';

-- a customer checks out 2 x MASK-001 to Vancouver, BC (12% tax on goods + shipping)
INSERT INTO orders (order_id, account_id, contact_name, ship_line1, ship_city, ship_region,
                    ship_postal_code, ship_country, bill_line1, bill_city, bill_region,
                    bill_postal_code, bill_country, shipping_method, subtotal, shipping_cost,
                    tax_amount, total_amount, checkout_token)
VALUES (900001, 1, 'Demo Customer', '100 Harbour St', 'Vancouver', 'BC', 'V6B 1A1', 'CA',
        '100 Harbour St', 'Vancouver', 'BC', 'V6B 1A1', 'CA', 'STANDARD',
        149.90, 12.00, 19.43, 181.33, '00000000-0000-4000-8000-000000900001');
INSERT INTO order_items (order_id, product_id, quantity, unit_price, line_total)
SELECT 900001, product_id, 2, 74.95, 149.90 FROM products WHERE sku = 'MASK-001';
INSERT INTO payments (payment_id, order_id, amount, method_type, token, last4, card_brand, status, gateway_ref)
VALUES (900001, 900001, 181.33, 'CREDIT_CARD', 'tok_fake_demo0001', '4242', 'Visa', 'CAPTURED', 'fake_ch_demo0001');

-- confirming the order fires trg_orders_take_stock
UPDATE orders
   SET status = 'CONFIRMED', confirmed_payment_id = 900001, confirmed_at = now()
 WHERE order_id = 900001;

-- stock after (2 lower) and the SALE movement the trigger wrote
SELECT sku, stock_quantity FROM products WHERE sku = 'MASK-001';
SELECT product_id, change_qty, reason, reference_order_id
FROM inventory_movements WHERE reference_order_id = 900001;

-- now try to confirm an order for 500 whistles: the trigger rejects it
SAVEPOINT before_oversell;
INSERT INTO orders (order_id, account_id, contact_name, ship_line1, ship_city, ship_region,
                    ship_postal_code, ship_country, bill_line1, bill_city, bill_region,
                    bill_postal_code, bill_country, shipping_method, subtotal, shipping_cost,
                    tax_amount, total_amount, checkout_token)
VALUES (900002, 1, 'Demo Customer', '100 Harbour St', 'Vancouver', 'BC', 'V6B 1A1', 'CA',
        '100 Harbour St', 'Vancouver', 'BC', 'V6B 1A1', 'CA', 'STANDARD',
        6250.00, 0.00, 750.00, 7000.00, '00000000-0000-4000-8000-000000900002');
INSERT INTO order_items (order_id, product_id, quantity, unit_price, line_total)
SELECT 900002, product_id, 500, 12.50, 6250.00 FROM products WHERE sku = 'WHISTLE-001';
INSERT INTO payments (payment_id, order_id, amount, method_type, token, last4, card_brand, status, gateway_ref)
VALUES (900002, 900002, 7000.00, 'CREDIT_CARD', 'tok_fake_demo0002', '4242', 'Visa', 'AUTHORIZED', 'fake_ch_demo0002');
-- EXPECTED ERROR: Out of stock: WHISTLE-001
UPDATE orders
   SET status = 'CONFIRMED', confirmed_payment_id = 900002, confirmed_at = now()
 WHERE order_id = 900002;
ROLLBACK TO SAVEPOINT before_oversell;

-- the failed confirmation changed nothing: whistle stock is untouched
SELECT sku, stock_quantity FROM products WHERE sku = 'WHISTLE-001';

ROLLBACK;
