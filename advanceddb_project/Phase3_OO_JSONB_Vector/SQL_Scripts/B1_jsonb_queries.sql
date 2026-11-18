-- B1  Part B: JSONB for attributes that vary from product to product
-- products.specs holds what differs per item: weight, colours[], sizes[] (array of objects),
-- features{} (nested object whose keys depend on the product type), certifications[],
-- compatible_with[] (array of objects pointing at other products by SKU).
-- product_reviews.details holds sub-ratings and the optional dive_context{} of a review.
-- This file makes NO lasting changes (J4 rolls back; J5 is rejected). 2 EXPECTED ERRORs.

-- what the varying attributes look like: three products, three different shapes
SELECT sku, product_kind, jsonb_pretty(specs) AS specs
FROM products WHERE sku IN ('SUIT-002', 'COMP-002', 'REG-001') ORDER BY sku;

-- which top-level keys appear, and how often (they vary by product, so they are not columns)
SELECT key, count(*) AS products_with_key
FROM products, jsonb_object_keys(specs) AS key
GROUP BY key ORDER BY products_with_key DESC, key;

-- ---------------------------------------------------------------------------
-- J1  Containment (@>): "show me nitrox-capable dive computers"
-- ---------------------------------------------------------------------------
SELECT sku, name, unit_price,
       specs #>> '{features,max_o2_pct}' AS max_o2_pct,
       specs #>> '{features,gas_mixes}'  AS gas_mixes,
       specs #>> '{features,algorithm}'  AS algorithm
FROM products
WHERE specs @> '{"features": {"nitrox": true}}'
ORDER BY unit_price
LIMIT 10;

SELECT count(*) AS nitrox_computers FROM products WHERE specs @> '{"features": {"nitrox": true}}';

-- EXPLAIN for J1 as the planner chooses it
EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT sku, name FROM products WHERE specs @> '{"features": {"nitrox": true}}';

-- size of the table vs the index: the whole table is only a handful of 8 kB pages
SELECT pg_size_pretty(pg_relation_size('products'))           AS products_heap,
       (SELECT relpages FROM pg_class WHERE relname = 'products') AS heap_pages,
       pg_size_pretty(pg_relation_size('products_specs_gin')) AS gin_index;

-- the same query with sequential scans discouraged: proves the GIN index CAN answer @>
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT sku, name FROM products WHERE specs @> '{"features": {"nitrox": true}}';
RESET enable_seqscan;

-- on the larger reviews table (2,390 rows) a selective containment uses its GIN index by itself
EXPLAIN (ANALYZE, BUFFERS, COSTS)
SELECT review_id FROM product_reviews WHERE details @> '{"dive_context": {"site": "Les Escoumins"}}';

-- ---------------------------------------------------------------------------
-- J2  JSON path (@? and jsonb_path_query): "which wetsuits / fins / BCDs have a size that is
--     currently unavailable, and which sizes?"
-- ---------------------------------------------------------------------------
SELECT p.sku, p.name,
       jsonb_path_query_array(p.specs, '$.sizes[*] ? (@.available == false).size') AS unavailable_sizes
FROM products p
WHERE p.specs @? '$.sizes[*] ? (@.available == false)'
ORDER BY p.sku
LIMIT 12;

-- jsonpath with a numeric filter on a nested value: cold dives (<= 6 C) logged in reviews
SELECT review_id, jsonb_path_query(details, '$.dive_context ? (@.water_temp_c <= 6)') AS cold_dive
FROM product_reviews
ORDER BY review_id
LIMIT 5;

-- ---------------------------------------------------------------------------
-- J3  JSON array -> rows, joined to a relational table: "what is REG-001 compatible with,
--     and is that gear in stock?" (compatible_with[] holds SKUs; products is relational)
-- ---------------------------------------------------------------------------
SELECT p.sku AS product, c.sku AS compatible_sku, c.note,
       q.name AS compatible_name, q.unit_price, q.stock_quantity, q.product_kind
FROM products p
CROSS JOIN LATERAL jsonb_to_recordset(p.specs -> 'compatible_with') AS c(sku TEXT, note TEXT)
JOIN products q ON q.sku = c.sku
WHERE p.sku = 'REG-001'
ORDER BY c.sku;

-- the same unnesting for the whole catalogue: sizes[] -> rows, joined back to categories
SELECT cat.name AS category, s.size, count(*) AS products, count(*) FILTER (WHERE NOT s.available) AS unavailable
FROM products p
JOIN categories cat ON cat.category_id = p.category_id
CROSS JOIN LATERAL jsonb_to_recordset(p.specs -> 'sizes') AS s(size TEXT, available BOOLEAN)
WHERE p.product_kind = 'WEARABLE'
GROUP BY cat.name, s.size
ORDER BY cat.name, min(p.product_id), s.size
LIMIT 12;

-- ---------------------------------------------------------------------------
-- J4  Update one nested value (jsonb_set): size M of SUIT-002 sells out; and one nested
--     feature of COMP-001 changes. Rolled back so the demo leaves the data unchanged.
-- ---------------------------------------------------------------------------
BEGIN;
SELECT sku, specs -> 'sizes' -> 2 AS size_m_before FROM products WHERE sku = 'SUIT-002';

UPDATE products
SET specs = jsonb_set(specs,
                      ARRAY['sizes', (SELECT (i - 1)::text
                                      FROM jsonb_array_elements(specs -> 'sizes') WITH ORDINALITY AS a(e, i)
                                      WHERE e ->> 'size' = 'M'), 'available'],
                      'false'),
    updated_at = now()
WHERE sku = 'SUIT-002';

UPDATE products
SET specs = jsonb_set(specs, '{features,max_o2_pct}', '50')
WHERE sku = 'COMP-001';

SELECT sku, specs -> 'sizes' -> 2 AS size_m_after FROM products WHERE sku = 'SUIT-002';
SELECT sku, specs -> 'features' AS features_after FROM products WHERE sku = 'COMP-001';
ROLLBACK;

-- ---------------------------------------------------------------------------
-- J5  The CHECK constraint products_specs_valid guards the JSON shape
-- ---------------------------------------------------------------------------
-- EXPECTED ERROR: violates check constraint "products_specs_valid" (weight_g is required)
UPDATE products SET specs = specs - 'weight_g' WHERE sku = 'MASK-001';

-- EXPECTED ERROR: violates check constraint "products_specs_valid" (a size without "available")
UPDATE products SET specs = jsonb_set(specs, '{sizes,0}', '{"size": "XS"}') WHERE sku = 'SUIT-002';
