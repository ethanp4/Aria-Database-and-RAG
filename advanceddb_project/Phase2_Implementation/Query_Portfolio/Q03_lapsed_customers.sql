-- Q03  Lapsed customers (win-back list)
-- Business question: Which customers bought from us in our first quarter (Oct-Dec 2025) but
--   have not placed a paid order in the last 120 days? Who are the most valuable of them?
-- Techniques: nested queries: IN (subquery), NOT EXISTS (correlated subquery), and
--   correlated scalar subqueries in the SELECT list.
-- The dataset is fixed as of 2026-10-01; in production replace the literal with now().

SELECT a.username,
       p.first_name || ' ' || p.last_name AS customer,
       (SELECT min(o.created_at)::date
          FROM orders o
         WHERE o.account_id = a.account_id AND o.confirmed_payment_id IS NOT NULL) AS first_order,
       (SELECT max(o.created_at)::date
          FROM orders o
         WHERE o.account_id = a.account_id AND o.confirmed_payment_id IS NOT NULL) AS last_order,
       (SELECT count(*)
          FROM orders o
         WHERE o.account_id = a.account_id AND o.confirmed_payment_id IS NOT NULL) AS paid_orders,
       (SELECT sum(o.total_amount)
          FROM orders o
         WHERE o.account_id = a.account_id AND o.confirmed_payment_id IS NOT NULL) AS lifetime_spend
FROM accounts a
JOIN profiles p ON p.account_id = a.account_id
WHERE a.account_type = 'user'
  -- bought in the first quarter
  AND a.account_id IN (SELECT o.account_id
                         FROM orders o
                        WHERE o.confirmed_payment_id IS NOT NULL
                          AND o.created_at >= TIMESTAMPTZ '2025-10-01 00:00+00'
                          AND o.created_at <  TIMESTAMPTZ '2026-01-01 00:00+00')
  -- ...and nothing paid in the last 120 days
  AND NOT EXISTS (SELECT 1
                    FROM orders o
                   WHERE o.account_id = a.account_id
                     AND o.confirmed_payment_id IS NOT NULL
                     AND o.created_at >= TIMESTAMPTZ '2026-10-01 00:00+00' - INTERVAL '120 days')
ORDER BY lifetime_spend DESC;
