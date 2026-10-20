-- Q01  Monthly revenue KPIs
-- Business question: How much did we sell each month, how much did we give back in refunds,
--   what is the average order value, and is revenue growing month over month?
-- Techniques: CTEs, aggregation with GROUP BY, LEFT JOIN of two aggregates, window function LAG().
-- Used by: admin analytics dashboard (revenue trend chart).
-- Note: "gross" includes shipping and tax because it is what customers paid. Only orders with
--   a captured payment count (confirmed_payment_id IS NOT NULL); failed and cancelled checkouts don't.
--   Refunds are counted in the month they were paid out.

WITH monthly_sales AS (
    SELECT date_trunc('month', o.confirmed_at) AS month,
           count(*)                            AS orders,
           sum(o.subtotal)                     AS merchandise,
           sum(o.total_amount)                 AS gross_revenue
    FROM orders o
    WHERE o.confirmed_payment_id IS NOT NULL
    GROUP BY 1
),
monthly_refunds AS (
    SELECT date_trunc('month', r.resolved_at) AS month,
           count(*)                           AS refunds,
           sum(r.amount)                      AS refunded
    FROM refunds r
    WHERE r.status = 'COMPLETED'
    GROUP BY 1
)
SELECT to_char(s.month, 'YYYY-MM')                          AS month,
       s.orders,
       s.merchandise,
       s.gross_revenue,
       COALESCE(r.refunded, 0)                               AS refunded,
       s.gross_revenue - COALESCE(r.refunded, 0)             AS net_revenue,
       round(s.gross_revenue / s.orders, 2)                  AS avg_order_value,
       round(100.0 * COALESCE(r.refunded, 0) / s.gross_revenue, 1) AS refund_pct,
       round(100.0 * (s.gross_revenue - lag(s.gross_revenue) OVER w)
                   / lag(s.gross_revenue) OVER w, 1)         AS gross_growth_pct
FROM monthly_sales s
LEFT JOIN monthly_refunds r ON r.month = s.month
WINDOW w AS (ORDER BY s.month)
ORDER BY s.month;
