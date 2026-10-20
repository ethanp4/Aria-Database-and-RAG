-- Q04  Reorder report (resource use)
-- Business question: Which active products are at or below their reorder level, or will run out
--   within 30 days at the current sales rate? When did we last restock them?
-- Techniques: LATERAL subquery (per-product sales velocity), correlated scalar subquery
--   (last restock), derived table filtered on a computed column, NULLIF to avoid divide-by-zero.
-- Index support: idx_inv_mov_product_created (product_id, created_at DESC).
-- The dataset is fixed as of 2026-10-01; in production replace the literal with now().

SELECT category, sku, product, stock_quantity, reorder_level,
       units_sold_90d, days_of_cover, last_restock
FROM (
    SELECT c.name                 AS category,
           p.sku,
           p.name                 AS product,
           p.stock_quantity,
           p.reorder_level,
           s.units_sold_90d,
           -- days until empty at the average daily sales rate of the last 90 days
           round(p.stock_quantity / NULLIF(s.units_sold_90d / 90.0, 0), 0) AS days_of_cover,
           (SELECT max(m.created_at)::date
              FROM inventory_movements m
             WHERE m.product_id = p.product_id AND m.reason = 'RESTOCK') AS last_restock
    FROM products p
    JOIN categories c ON c.category_id = p.category_id
    CROSS JOIN LATERAL (
        SELECT COALESCE(-sum(m.change_qty), 0) AS units_sold_90d
        FROM inventory_movements m
        WHERE m.product_id = p.product_id
          AND m.reason = 'SALE'
          AND m.created_at >= TIMESTAMPTZ '2026-10-01 00:00+00' - INTERVAL '90 days'
    ) s
    WHERE p.is_active
) r
WHERE stock_quantity <= reorder_level
   OR days_of_cover < 30
ORDER BY stock_quantity <= reorder_level DESC, days_of_cover NULLS LAST, category;
