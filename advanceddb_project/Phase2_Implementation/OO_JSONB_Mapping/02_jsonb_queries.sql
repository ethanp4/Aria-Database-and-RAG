-- OO / JSONB mapping, part 2: queries that read inside the order documents.
-- Run while connected to aria_phase2, after 01_order_document.sql.

-- J1  Containment (@>) on nested objects
-- Business question: Which delivered orders went to British Columbia by Canada Post?
--   (A regional carrier review.) One @> matches fields at three nesting levels at once.
SELECT order_id,
       doc -> 'customer' ->> 'username'          AS customer,
       doc -> 'shipping_address' ->> 'city'      AS city,
       doc -> 'shipment' ->> 'tracking_number'   AS tracking_number,
       (doc -> 'totals' ->> 'total')::numeric    AS total
FROM order_document
WHERE doc @> '{"status": "DELIVERED",
               "shipping_address": {"region": "BC"},
               "shipment": {"carrier": "Canada Post"}}'
ORDER BY order_id
LIMIT 10;

-- The GIN index answers that predicate. At 480 documents a sequential scan is cheaper, so the
-- planner normally skips the index; disabling seq scans for this one EXPLAIN shows the plan
-- PostgreSQL uses once the table is large.
BEGIN;
SET LOCAL enable_seqscan = off;
EXPLAIN (COSTS OFF)
SELECT order_id FROM order_document
WHERE doc @> '{"status": "DELIVERED", "shipping_address": {"region": "BC"}, "shipment": {"carrier": "Canada Post"}}';
ROLLBACK;

-- J2  Unnest an embedded array (jsonb_array_elements)
-- Business question: Units and revenue per category, computed from the documents alone,
--   for paid orders. (What an export consumer or API client would do.)
SELECT item ->> 'category'                         AS category,
       sum((item ->> 'quantity')::int)             AS units,
       sum((item ->> 'line_total')::numeric)       AS revenue
FROM order_document d
CROSS JOIN LATERAL jsonb_array_elements(d.doc -> 'items') AS item
WHERE d.doc ->> 'status' IN ('CONFIRMED', 'SHIPPED', 'DELIVERED', 'REFUNDED')
GROUP BY 1
ORDER BY revenue DESC;

-- J3  SQL/JSON path filter inside an array (@? and jsonb_path_query)
-- Business question: Which orders contain at least one item over $500, and which items are they?
--   (High-value orders get signature-on-delivery.)
SELECT order_id,
       doc -> 'shipment' ->> 'method'                                      AS shipping_method,
       jsonb_path_query_array(doc, '$.items[*] ? (@.unit_price > 500).sku') AS high_value_skus
FROM order_document
WHERE doc @? '$.items[*] ? (@.unit_price > 500)'
ORDER BY order_id
LIMIT 10;

-- J4  Polymorphic embedded object (the CardPayment / WalletPayment subclasses)
-- Business question: How are paid orders split between card and wallet payments?
SELECT doc -> 'payment' ->> 'type'          AS payment_type,
       doc -> 'payment' ->> 'method'        AS method,
       count(*)                             AS orders,
       sum((doc -> 'totals' ->> 'total')::numeric) AS value
FROM order_document
WHERE doc -> 'payment' ->> 'status' IN ('CAPTURED', 'REFUNDED')
GROUP BY 1, 2
ORDER BY orders DESC;

-- J5  Consistency check: the read model agrees with the authoritative relational tables
-- Business question: Has any document drifted from the orders table? (Must return 0 rows.)
SELECT o.order_id, o.status, d.doc ->> 'status' AS doc_status,
       o.total_amount, (d.doc -> 'totals' ->> 'total')::numeric AS doc_total
FROM orders o
JOIN order_document d ON d.order_id = o.order_id
WHERE o.status <> d.doc ->> 'status'
   OR o.total_amount <> (d.doc -> 'totals' ->> 'total')::numeric
   OR (SELECT count(*) FROM order_items oi WHERE oi.order_id = o.order_id)
      <> jsonb_array_length(d.doc -> 'items');

-- J6  Schema flexibility: add an optional field to one document with no ALTER TABLE
-- (rolled back). A relational design would need a new nullable column for every such field.
BEGIN;
UPDATE order_document
   SET doc = jsonb_set(doc, '{gift}', '{"wrapped": true, "message": "Happy diving!"}')
 WHERE order_id = (SELECT min(order_id) FROM order_document);
SELECT order_id, doc -> 'gift' AS gift
FROM order_document
WHERE doc ? 'gift';
ROLLBACK;
