-- Q12  Customer lifetime value tiers
-- Business question: How is revenue spread across our customers? How much of net revenue comes
--   from the top 25%, and what does a typical customer in each tier look like?
--   (Used to decide who gets loyalty perks and win-back offers.)
-- Techniques: chained CTEs, NTILE() window function, aggregate over a window
--   (sum(sum(...)) OVER ()) for share of total, LEFT JOIN to net out refunds.

WITH customer_orders AS (
    SELECT o.account_id,
           count(*)            AS paid_orders,
           sum(o.total_amount) AS gross_spend,
           min(o.created_at)   AS first_order,
           max(o.created_at)   AS last_order
    FROM orders o
    WHERE o.account_id IS NOT NULL
      AND o.confirmed_payment_id IS NOT NULL
    GROUP BY o.account_id
),
customer_refunds AS (
    SELECT o.account_id, sum(r.amount) AS refunded
    FROM refunds r
    JOIN orders o ON o.order_id = r.order_id
    WHERE r.status = 'COMPLETED'
    GROUP BY o.account_id
),
clv AS (
    SELECT co.*,
           co.gross_spend - COALESCE(cr.refunded, 0)                            AS net_value,
           ntile(4) OVER (ORDER BY co.gross_spend - COALESCE(cr.refunded, 0) DESC) AS quartile
    FROM customer_orders co
    LEFT JOIN customer_refunds cr ON cr.account_id = co.account_id
)
SELECT CASE quartile WHEN 1 THEN '1 Top 25%' WHEN 2 THEN '2 Upper-mid 25%'
                     WHEN 3 THEN '3 Lower-mid 25%' ELSE '4 Bottom 25%' END   AS tier,
       count(*)                                                            AS customers,
       round(avg(paid_orders), 2)                                          AS avg_orders,
       round(avg(net_value), 2)                                            AS avg_net_value,
       min(net_value)                                                      AS min_net_value,
       sum(net_value)                                                      AS tier_net_value,
       round(100 * sum(net_value) / sum(sum(net_value)) OVER (), 1)        AS pct_of_net_revenue
FROM clv
GROUP BY quartile
ORDER BY quartile;
