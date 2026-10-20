-- Q05  Return rate by category, and why customers ask for refunds
-- Business question (a): Which categories have the highest share of sold units returned to stock?
--   (Fit problems with fins and wetsuits would show up here first.)
-- Business question (b): For each refund reason, how many requests do we get, how many do we
--   approve, and how much money goes back?
-- Techniques: aggregate FILTER clauses, LEFT JOIN to keep categories with no returns,
--   conditional aggregation, ratio KPIs.
-- Returned units come from REFUND movements in inventory_movements, so a refund for one line
-- of a mixed order is attributed to the right category.

-- (a) return rate by category
SELECT c.name                                                          AS category,
       COALESCE(-sum(m.change_qty) FILTER (WHERE m.reason = 'SALE'), 0)  AS units_sold,
       COALESCE(sum(m.change_qty) FILTER (WHERE m.reason = 'REFUND'), 0) AS units_returned,
       round(100.0 * COALESCE(sum(m.change_qty) FILTER (WHERE m.reason = 'REFUND'), 0)
                   / NULLIF(-sum(m.change_qty) FILTER (WHERE m.reason = 'SALE'), 0), 1) AS return_rate_pct
FROM categories c
JOIN products p ON p.category_id = c.category_id
LEFT JOIN inventory_movements m ON m.product_id = p.product_id
GROUP BY c.name
ORDER BY return_rate_pct DESC;

-- (b) refund outcomes by reason
SELECT r.reason,
       count(*)                                            AS requests,
       count(*) FILTER (WHERE r.status = 'COMPLETED')      AS completed,
       count(*) FILTER (WHERE r.status = 'DENIED')         AS denied,
       count(*) FILTER (WHERE r.status IN ('REQUESTED', 'APPROVED')) AS still_open,
       round(100.0 * count(*) FILTER (WHERE r.status = 'COMPLETED')
                   / NULLIF(count(*) FILTER (WHERE r.status IN ('COMPLETED', 'DENIED')), 0), 1) AS approval_rate_pct,
       COALESCE(sum(r.amount) FILTER (WHERE r.status = 'COMPLETED'), 0) AS refunded_amount,
       round(avg(r.risk_score), 1)                         AS avg_risk_score
FROM refunds r
GROUP BY r.reason
ORDER BY requests DESC;
