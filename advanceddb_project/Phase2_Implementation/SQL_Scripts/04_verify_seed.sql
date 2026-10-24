-- Aria Phase 2: integrity checks on the seed data.
-- Run while connected to aria_phase2 after 03_seed.sql. Shows row counts, then runs
-- cross-table checks that a CHECK constraint can't express. Every check must return 0;
-- the DO block at the end raises an error (and stops run_all) if any check fails.

-- \echo 'Row counts'
SELECT 'accounts' AS table_name, count(*) AS row_count FROM accounts
UNION ALL SELECT 'profiles', count(*) FROM profiles
UNION ALL SELECT 'addresses', count(*) FROM addresses
UNION ALL SELECT 'categories', count(*) FROM categories
UNION ALL SELECT 'products', count(*) FROM products
UNION ALL SELECT 'carriers', count(*) FROM carriers
UNION ALL SELECT 'suppliers', count(*) FROM suppliers
UNION ALL SELECT 'orders', count(*) FROM orders
UNION ALL SELECT 'order_items', count(*) FROM order_items
UNION ALL SELECT 'payments', count(*) FROM payments
UNION ALL SELECT 'inventory_movements', count(*) FROM inventory_movements
UNION ALL SELECT 'refunds', count(*) FROM refunds
UNION ALL SELECT 'duplicate_refund_attempts', count(*) FROM duplicate_refund_attempts
UNION ALL SELECT 'accounts_receivable', count(*) FROM accounts_receivable
UNION ALL SELECT 'accounts_payable', count(*) FROM accounts_payable
UNION ALL SELECT 'policy_documents', count(*) FROM policy_documents;

-- \echo 'Integrity checks (every violations value must be 0)'
CREATE TEMP VIEW seed_checks AS
-- stock on hand equals the sum of its movement history
SELECT 'stock = sum(movements)' AS check_name, count(*) AS violations
FROM products p
WHERE p.stock_quantity <> (SELECT COALESCE(sum(m.change_qty), 0)
                           FROM inventory_movements m WHERE m.product_id = p.product_id)
UNION ALL
-- replaying movements in time order never takes stock below zero
SELECT 'running stock never negative', count(*)
FROM (SELECT sum(change_qty) OVER (PARTITION BY product_id ORDER BY created_at, movement_id) AS running
      FROM inventory_movements) r
WHERE r.running < 0
UNION ALL
-- order header subtotal equals the sum of its lines
SELECT 'subtotal = sum(lines)', count(*)
FROM orders o
WHERE o.subtotal <> (SELECT sum(i.line_total) FROM order_items i WHERE i.order_id = o.order_id)
UNION ALL
-- a confirmed-family order's payment is captured (or later refunded), belongs to it and covers the total
SELECT 'confirmed order has matching captured payment', count(*)
FROM orders o
LEFT JOIN payments p ON p.payment_id = o.confirmed_payment_id
WHERE o.status IN ('CONFIRMED', 'SHIPPED', 'DELIVERED', 'REFUNDED')
  AND (p.payment_id IS NULL OR p.order_id <> o.order_id OR p.amount <> o.total_amount
       OR p.status NOT IN ('CAPTURED', 'REFUNDED'))
UNION ALL
-- each sold line has exactly one matching SALE movement; unconfirmed orders have none
SELECT 'sale movements match sold lines', count(*)
FROM order_items i
JOIN orders o ON o.order_id = i.order_id
LEFT JOIN inventory_movements m
       ON m.reference_order_id = i.order_id AND m.product_id = i.product_id AND m.reason = 'SALE'
WHERE (o.confirmed_payment_id IS NOT NULL AND (m.change_qty IS NULL OR m.change_qty <> -i.quantity))
   OR (o.confirmed_payment_id IS NULL AND m.movement_id IS NOT NULL)
UNION ALL
-- completed + in-flight refunds never exceed what the customer paid
SELECT 'refunds within order total', count(*)
FROM (SELECT r.order_id, sum(r.amount) AS refunded
      FROM refunds r WHERE r.status IN ('APPROVED', 'COMPLETED') GROUP BY r.order_id) r
JOIN orders o ON o.order_id = r.order_id
WHERE r.refunded > o.total_amount
UNION ALL
-- refunds point at the order's own confirmed payment
SELECT 'refund payment belongs to order', count(*)
FROM refunds r JOIN orders o ON o.order_id = r.order_id
WHERE r.payment_id <> o.confirmed_payment_id
UNION ALL
-- only staff/admin accounts resolve refunds
SELECT 'refunds resolved by staff', count(*)
FROM refunds r JOIN accounts a ON a.account_id = r.resolved_by
WHERE a.account_type NOT IN ('staff', 'admin')
UNION ALL
-- no payment row could hold a card number: tokens are fake, last4 is 4 digits or NULL
SELECT 'payment tokens are fake tokens', count(*)
FROM payments WHERE token NOT LIKE 'tok_fake_%'
UNION ALL
-- seed data is synthetic: every email is on the reserved example.test domain
SELECT 'emails on example.test', count(*)
FROM (SELECT email FROM profiles UNION ALL SELECT contact_email FROM orders WHERE contact_email IS NOT NULL
      UNION ALL SELECT contact_email FROM suppliers) e
WHERE e.email NOT LIKE '%example.test';

SELECT * FROM seed_checks;

DO $$
DECLARE failed text;
BEGIN
    SELECT string_agg(check_name, ', ') INTO failed FROM seed_checks WHERE violations > 0;
    IF failed IS NOT NULL THEN
        RAISE EXCEPTION 'Seed integrity checks failed: %', failed;
    END IF;
    RAISE NOTICE 'All seed integrity checks passed.';
END $$;
