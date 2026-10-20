-- Q07  Payment outcomes by method and card brand
-- Business question: How often does each payment method get declined or abandoned, and how much
--   captured revenue does each method bring in? (Tells us which methods cost us sales.)
-- Techniques: GROUPING SETS for brand rows + method subtotals + grand total in one pass,
--   GROUPING() to label subtotal rows, FILTER aggregates.
-- Payment details are summarized only; tokens never leave the payments table.

SELECT CASE WHEN grouping(p.method_type) = 1 THEN 'ALL METHODS' ELSE p.method_type END AS method,
       CASE WHEN grouping(p.method_type) = 1 THEN ''
            WHEN grouping(p.card_brand) = 1 THEN '(subtotal)'
            ELSE COALESCE(NULLIF(p.card_brand, ''), '-') END                             AS brand,
       count(*)                                                       AS attempts,
       count(*) FILTER (WHERE p.status IN ('CAPTURED', 'REFUNDED'))   AS captured,
       count(*) FILTER (WHERE p.status = 'DECLINED')                  AS declined,
       count(*) FILTER (WHERE p.status = 'VOIDED')                    AS voided,
       round(100.0 * count(*) FILTER (WHERE p.status = 'DECLINED') / count(*), 1) AS decline_rate_pct,
       COALESCE(sum(p.amount) FILTER (WHERE p.status IN ('CAPTURED', 'REFUNDED')), 0) AS captured_value
FROM payments p
GROUP BY GROUPING SETS ((p.method_type, p.card_brand), (p.method_type), ())
ORDER BY grouping(p.method_type), p.method_type, grouping(p.card_brand), brand;
