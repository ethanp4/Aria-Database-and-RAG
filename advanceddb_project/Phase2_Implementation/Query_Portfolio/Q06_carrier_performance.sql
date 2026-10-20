-- Q06  Carrier performance and cost (performance report)
-- Business question: Which carrier gets parcels to customers fastest and most reliably, and what
--   does each one cost us per shipment? (Input for renegotiating or re-routing carrier volume.)
-- Techniques: multi-CTE report joining orders, carriers and accounts_payable; ordered-set
--   aggregates percentile_cont(); CASE for the delivery promise; FILTER for on-time share.
-- Promise used: STANDARD 7 days, EXPRESS 4, PRIORITY 3, plus 2 days for US (cross-border).

WITH deliveries AS (
    SELECT o.carrier_id,
           extract(epoch FROM o.delivered_at - o.shipped_at) / 86400.0 AS transit_days,
           CASE o.shipping_method WHEN 'STANDARD' THEN 7 WHEN 'EXPRESS' THEN 4 ELSE 3 END
             + CASE WHEN o.ship_country = 'US' THEN 2 ELSE 0 END    AS promised_days
    FROM orders o
    WHERE o.delivered_at IS NOT NULL
),
shipments AS (
    SELECT carrier_id, count(*) AS shipped
    FROM orders
    WHERE shipped_at IS NOT NULL
    GROUP BY carrier_id
),
billed AS (
    -- what the carrier invoiced us (accounts_payable rows whose payee is a carrier)
    SELECT carrier_id, sum(amount_due) AS billed
    FROM accounts_payable
    WHERE carrier_id IS NOT NULL
    GROUP BY carrier_id
)
SELECT c.name                                                      AS carrier,
       s.shipped,
       count(d.*)                                                  AS delivered,
       round(avg(d.transit_days)::numeric, 1)                      AS avg_days,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY d.transit_days)::numeric, 1) AS median_days,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY d.transit_days)::numeric, 1) AS p90_days,
       round(100.0 * count(*) FILTER (WHERE d.transit_days <= d.promised_days) / count(d.*), 1) AS on_time_pct,
       b.billed,
       round(b.billed / s.shipped, 2)                              AS cost_per_shipment
FROM carriers c
JOIN shipments s  ON s.carrier_id = c.carrier_id
JOIN deliveries d ON d.carrier_id = c.carrier_id
LEFT JOIN billed b ON b.carrier_id = c.carrier_id
GROUP BY c.name, s.shipped, b.billed
ORDER BY on_time_pct DESC;
