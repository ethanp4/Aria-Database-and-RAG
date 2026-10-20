-- Q13  Query optimization with an index, at the 1,000,000-orders scale
-- Business question: The "My orders" page shows a customer's 10 most recent orders. Will that
--   stay fast at our scale target (1,000,000 transactions/month)?
-- Techniques: EXPLAIN (ANALYZE) before and after a composite index; ANALYZE to refresh planner
--   statistics; a TEMP table built with generate_series() so the test doesn't touch real data.
--
-- At 480 seed orders every plan finishes in well under a millisecond, so the difference only
-- shows at volume. This builds 1,000,000 synthetic rows with the same access pattern
-- (50,000 customers, timestamps over one month), then compares the plans.
-- Exact timings vary by machine; the plan shapes are the point.

DROP TABLE IF EXISTS orders_at_scale;
CREATE TEMP TABLE orders_at_scale AS
SELECT g                                                     AS order_id,
       (g * 7919) % 50000 + 1                                AS account_id,   -- spread over 50k customers
       TIMESTAMPTZ '2026-09-01 00:00+00' + g * INTERVAL '2.6 seconds' AS created_at,
       ((g * 104729) % 90000) / 100.0 + 10                   AS total_amount
FROM generate_series(1::bigint, 1000000) AS g;
ANALYZE orders_at_scale;

-- BEFORE: no index -> Seq Scan over 1M rows, then a top-N sort
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT order_id, created_at, total_amount
FROM orders_at_scale
WHERE account_id = 4242
ORDER BY created_at DESC
LIMIT 10;

-- the same index the real orders table has: idx_orders_account_created (account_id, created_at DESC)
CREATE INDEX ON orders_at_scale (account_id, created_at DESC);
ANALYZE orders_at_scale;

-- AFTER: Index Scan reads only this customer's newest rows, already in order (no sort step)
EXPLAIN (ANALYZE, COSTS OFF, SUMMARY ON)
SELECT order_id, created_at, total_amount
FROM orders_at_scale
WHERE account_id = 4242
ORDER BY created_at DESC
LIMIT 10;

DROP TABLE orders_at_scale;
