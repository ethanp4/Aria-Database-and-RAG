-- C2  Part C: vector similarity combined with a relational filter and a JSONB filter
-- Request (staff, handling a warranty claim): "find reviews where a REGULATOR or other
--   life-support item started free flowing in icy water", limited to life-support products
--   (relational: products.product_kind) and to dives logged at 8 C or colder
--   (JSONB: product_reviews.details -> dive_context -> water_temp_c).

\set f1 '(SELECT embedding FROM eval_queries WHERE query_id = ''F1'')'

SELECT row_number() OVER (ORDER BY e.embedding <=> :f1) AS rank,
       r.review_id, p.sku, p.product_kind,
       r.details #>> '{dive_context,site}'          AS site,
       r.details #>> '{dive_context,water_temp_c}'  AS water_c,
       round((e.embedding <=> :f1)::numeric, 4)     AS distance,
       left(r.body, 110)                            AS body
FROM review_embeddings e
JOIN product_reviews r USING (review_id)
JOIN products p USING (product_id)
WHERE p.product_kind = 'LIFE_SUPPORT'
  AND r.details @? '$.dive_context.water_temp_c ? (@ <= 8)'
ORDER BY e.embedding <=> :f1
LIMIT 5;

-- how many rows pass the two filters before ranking (the candidate set the planner sorts)
SELECT count(*) AS candidates_after_filters
FROM product_reviews r JOIN products p USING (product_id)
WHERE p.product_kind = 'LIFE_SUPPORT'
  AND r.details @? '$.dive_context.water_temp_c ? (@ <= 8)';

-- The plan the optimizer picks
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.review_id
FROM review_embeddings e
JOIN product_reviews r USING (review_id)
JOIN products p USING (product_id)
WHERE p.product_kind = 'LIFE_SUPPORT'
  AND r.details @? '$.dive_context.water_temp_c ? (@ <= 8)'
ORDER BY e.embedding <=> :f1
LIMIT 5;

-- For comparison: force the "index first, filter after" plan (HNSW scan, then filter each
-- neighbour). Same 5 rows here, because the nearest neighbours of this question already are
-- cold-water regulator reviews.
SET enable_sort = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.review_id
FROM review_embeddings e
JOIN product_reviews r USING (review_id)
JOIN products p USING (product_id)
WHERE p.product_kind = 'LIFE_SUPPORT'
  AND r.details @? '$.dive_context.water_temp_c ? (@ <= 8)'
ORDER BY e.embedding <=> :f1
LIMIT 5;

-- The risk of index-first filtering: HNSW returns only hnsw.ef_search (40) candidates. If the
-- filter rejects all of them, the query returns FEWER than LIMIT rows, silently. Same question,
-- but restricted to ACCESSORY products (whose reviews are far from "regulator free flow"):
SET hnsw.iterative_scan = off;
SELECT count(*) AS rows_returned_without_iterative_scan
FROM (SELECT r.review_id
      FROM review_embeddings e JOIN product_reviews r USING (review_id) JOIN products p USING (product_id)
      WHERE p.product_kind = 'ACCESSORY'
      ORDER BY e.embedding <=> :f1 LIMIT 5) s;

-- pgvector 0.8 fix: iterative index scans keep walking the graph until LIMIT rows pass the filter
SET hnsw.iterative_scan = relaxed_order;
SELECT count(*) AS rows_returned_with_iterative_scan
FROM (SELECT r.review_id
      FROM review_embeddings e JOIN product_reviews r USING (review_id) JOIN products p USING (product_id)
      WHERE p.product_kind = 'ACCESSORY'
      ORDER BY e.embedding <=> :f1 LIMIT 5) s;
RESET hnsw.iterative_scan;
RESET enable_sort;
