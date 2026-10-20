-- Q11  Transaction: checkout as one atomic unit
-- Business question: How do we make sure a checkout either fully happens (order, items,
--   captured payment, stock taken, movement logged) or leaves no trace, and that an order is
--   never shown as "Confirmed" unless the payment succeeded?
-- Techniques: explicit BEGIN / SAVEPOINT / ROLLBACK TO SAVEPOINT / COMMIT; READ COMMITTED with
--   SELECT ... FOR UPDATE row locks; the checkout_token UNIQUE constraint for double submits;
--   the orders_confirmed_requires_payment CHECK; the Q09 trigger taking stock. Run Q09 first.
--
-- The app's place_order() follows the same steps. This script ends with ROLLBACK so the seed
-- data stays reproducible; in production the last statement is COMMIT.

BEGIN ISOLATION LEVEL READ COMMITTED;

-- 1. create the order (status PENDING_PAYMENT) and its lines.
--    checkout_token is UNIQUE: a double-submitted form can't create a second order.
INSERT INTO orders (order_id, account_id, contact_name, ship_line1, ship_city, ship_region,
                    ship_postal_code, ship_country, bill_line1, bill_city, bill_region,
                    bill_postal_code, bill_country, shipping_method, subtotal, shipping_cost,
                    tax_amount, total_amount, checkout_token)
VALUES (900101, 2, 'Demo Customer', '22 Tide Way', 'Halifax', 'NS', 'B3J 2K9', 'CA',
        '22 Tide Way', 'Halifax', 'NS', 'B3J 2K9', 'CA', 'EXPRESS',
        113.95, 20.00, 18.75, 152.70, '00000000-0000-4000-8000-000000900101');
INSERT INTO order_items (order_id, product_id, quantity, unit_price, line_total)
SELECT 900101, product_id, 1, 74.95, 74.95 FROM products WHERE sku = 'MASK-001'
UNION ALL
SELECT 900101, product_id, 1, 39.00, 39.00 FROM products WHERE sku = 'REEL-001';

-- 2. lock the products being bought (fixed order) so a concurrent buyer waits here
SELECT product_id, sku, stock_quantity
FROM products
WHERE sku IN ('MASK-001', 'REEL-001')
ORDER BY product_id
FOR UPDATE;

-- 3. a double submit replays the same checkout_token. EXPECTED ERROR: duplicate key
SAVEPOINT before_replay;
INSERT INTO orders (account_id, contact_name, ship_line1, ship_city, ship_region,
                    ship_postal_code, ship_country, bill_line1, bill_city, bill_region,
                    bill_postal_code, bill_country, shipping_method, subtotal, shipping_cost,
                    tax_amount, total_amount, checkout_token)
VALUES (2, 'Demo Customer', '22 Tide Way', 'Halifax', 'NS', 'B3J 2K9', 'CA',
        '22 Tide Way', 'Halifax', 'NS', 'B3J 2K9', 'CA', 'EXPRESS',
        113.95, 20.00, 18.75, 152.70, '00000000-0000-4000-8000-000000900101');
ROLLBACK TO SAVEPOINT before_replay;

-- 4. invariant 1: the order can't be marked CONFIRMED before a payment exists.
--    EXPECTED ERROR: violates check constraint "orders_confirmed_requires_payment"
SAVEPOINT before_confirm;
UPDATE orders SET status = 'CONFIRMED', confirmed_at = now() WHERE order_id = 900101;
ROLLBACK TO SAVEPOINT before_confirm;

-- 5. payment captured by the (fake) gateway: store token + last 4 digits only
INSERT INTO payments (payment_id, order_id, amount, method_type, token, last4, card_brand, status, gateway_ref)
VALUES (900101, 900101, 152.70, 'CREDIT_CARD', 'tok_fake_demo0101', '4444', 'Mastercard', 'CAPTURED', 'fake_ch_demo0101');

-- 6. confirm: the trigger checks and takes stock in this same transaction
UPDATE orders
   SET status = 'CONFIRMED', confirmed_payment_id = 900101, confirmed_at = now()
 WHERE order_id = 900101;

-- 7. everything is visible inside the transaction
SELECT order_id, status, total_amount, payment, payment_status, item_lines
FROM v_order_summary WHERE order_id = 900101;
SELECT p.sku, p.stock_quantity, m.change_qty, m.reason
FROM inventory_movements m JOIN products p ON p.product_id = m.product_id
WHERE m.reference_order_id = 900101
ORDER BY p.sku;

-- 8. production: COMMIT. Demo: ROLLBACK, after which none of the rows above exist.
ROLLBACK;

SELECT count(*) AS demo_orders_left FROM orders WHERE order_id = 900101;
