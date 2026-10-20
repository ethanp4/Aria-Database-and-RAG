-- Q02  Top 3 products in each category by revenue
-- Business question: Which products drive each category's sales, and how concentrated is each
--   category on its best sellers? (Used for merchandising and which items to never let run out.)
-- Techniques: 4-table join, aggregation, window functions RANK() and SUM() OVER (PARTITION BY ...),
--   filtering on a window result through a CTE.

WITH product_sales AS (
    SELECT c.name                       AS category,
           p.sku,
           p.name                       AS product,
           count(DISTINCT o.order_id)   AS orders,
           sum(oi.quantity)             AS units,
           sum(oi.line_total)           AS revenue
    FROM order_items oi
    JOIN orders o     ON o.order_id = oi.order_id
    JOIN products p   ON p.product_id = oi.product_id
    JOIN categories c ON c.category_id = p.category_id
    WHERE o.confirmed_payment_id IS NOT NULL          -- paid orders only
    GROUP BY c.name, p.sku, p.name
),
ranked AS (
    SELECT ps.*,
           rank() OVER (PARTITION BY category ORDER BY revenue DESC)              AS rank_in_category,
           round(100 * revenue / sum(revenue) OVER (PARTITION BY category), 1)    AS pct_of_category
    FROM product_sales ps
)
SELECT category, rank_in_category, sku, product, orders, units, revenue, pct_of_category
FROM ranked
WHERE rank_in_category <= 3
ORDER BY category, rank_in_category;
