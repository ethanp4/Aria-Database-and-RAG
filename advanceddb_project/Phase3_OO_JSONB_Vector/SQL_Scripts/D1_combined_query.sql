-- D1  Part D: one query that combines all three parts
--
-- The request, in plain English (a customer asking the store, or staff answering for them):
--   "I dive cold water in BC and I'm buying a nitrox-capable dive computer with at least a
--    two-year warranty. What are other divers saying about the battery draining fast in the cold?"
--
--   vector similarity  review embedding closest to "battery drains fast when diving in cold water"   (Part C)
--   class hierarchy    only DiveElectronics products (subclass), using the subclass attribute
--                      warranty_months >= 24 that exists only on that subclass                    (Part A)
--   JSONB              product specs contain {"features": {"nitrox": true}}                        (Part B)
--
-- The hierarchy is used through its public interface (v_product_catalogue), and the answer
-- includes the polymorphic kind_detail text, which for electronics describes battery and warranty.
-- iterative_scan makes sure filtering after the HNSW scan still returns 5 rows (see C2).

SET hnsw.iterative_scan = relaxed_order;

\set d1 '(SELECT embedding FROM eval_queries WHERE query_id = ''D1'')'

SELECT row_number() OVER (ORDER BY e.embedding <=> :d1)  AS rank,
       v.sku, v.name,
       v.kind_detail,
       v.specs #>> '{features,max_o2_pct}'                AS max_o2_pct,
       r.rating,
       r.details #>> '{dive_context,site}'                AS dive_site,
       r.details #>> '{dive_context,water_temp_c}'        AS water_c,
       round((e.embedding <=> :d1)::numeric, 4)           AS distance,
       left(r.body, 120)                                  AS what_the_diver_said
FROM review_embeddings e
JOIN product_reviews r     ON r.review_id = e.review_id
JOIN v_product_catalogue v ON v.product_id = r.product_id
WHERE v.product_kind = 'ELECTRONICS'                              -- hierarchy: subclass
  AND v.warranty_months >= 24                                     -- hierarchy: subclass-only attribute
  AND v.specs @> '{"features": {"nitrox": true}}'                 -- JSONB containment
ORDER BY e.embedding <=> :d1                                      -- vector similarity
LIMIT 5;

-- which products qualified (the candidate set before ranking)
SELECT v.sku, v.name, v.kind_detail, v.unit_price,
       (SELECT count(*) FROM product_reviews r WHERE r.product_id = v.product_id) AS reviews
FROM v_product_catalogue v
WHERE v.product_kind = 'ELECTRONICS'
  AND v.warranty_months >= 24
  AND v.specs @> '{"features": {"nitrox": true}}'
ORDER BY v.unit_price;

EXPLAIN (ANALYZE, COSTS OFF)
SELECT r.review_id
FROM review_embeddings e
JOIN product_reviews r     ON r.review_id = e.review_id
JOIN v_product_catalogue v ON v.product_id = r.product_id
WHERE v.product_kind = 'ELECTRONICS'
  AND v.warranty_months >= 24
  AND v.specs @> '{"features": {"nitrox": true}}'
ORDER BY e.embedding <=> :d1
LIMIT 5;

RESET hnsw.iterative_scan;
