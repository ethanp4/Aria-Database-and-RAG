-- C4  Part C: the same search with and without the HNSW index
-- HNSW is an APPROXIMATE nearest-neighbour index: it walks a graph and can, in principle, miss
-- a true neighbour. Without the index PostgreSQL computes the distance to every row and sorts
-- (exact k-NN). We run S4 both ways, compare the top 10, and time both.
-- Search: S4 "dive computer battery runs out too quickly"

\set s4 '(SELECT embedding FROM eval_queries WHERE query_id = ''S4'')'

-- with the index (default hnsw.ef_search = 40)
EXPLAIN (ANALYZE, BUFFERS)
SELECT review_id FROM review_embeddings ORDER BY embedding <=> :s4 LIMIT 10;
CREATE TEMP TABLE top10_hnsw AS
SELECT row_number() OVER (ORDER BY d) AS rank, review_id, d
FROM (SELECT review_id, embedding <=> :s4 AS d FROM review_embeddings ORDER BY embedding <=> :s4 LIMIT 10) s;

-- without the index: exact scan + sort
SET enable_indexscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT review_id FROM review_embeddings ORDER BY embedding <=> :s4 LIMIT 10;
CREATE TEMP TABLE top10_exact AS
SELECT row_number() OVER (ORDER BY d) AS rank, review_id, d
FROM (SELECT review_id, embedding <=> :s4 AS d FROM review_embeddings ORDER BY embedding <=> :s4 LIMIT 10) s;
RESET enable_indexscan;

-- side by side
SELECT x.rank, x.review_id AS exact_review, round(x.d::numeric, 4) AS exact_distance,
       h.review_id AS hnsw_review, round(h.d::numeric, 4) AS hnsw_distance,
       x.review_id = h.review_id AS same
FROM top10_exact x JOIN top10_hnsw h USING (rank)
ORDER BY x.rank;

SELECT count(*) AS top10_results_in_both, '10' AS out_of
FROM top10_exact x JOIN top10_hnsw h USING (review_id);

-- recall vs speed knob: overlap with the exact top 10 for every query at three ef_search values
CREATE TEMP TABLE recall (ef_search INT, query_id TEXT, overlap INT);
CREATE TEMP TABLE recall_a (review_id BIGINT);      -- top 10 via HNSW
CREATE TEMP TABLE recall_b (review_id BIGINT);      -- top 10 exact
DO $$
DECLARE
    ef INT;
    q  RECORD;
    n  INT;
BEGIN
    FOREACH ef IN ARRAY ARRAY[10, 40, 100] LOOP
        PERFORM set_config('hnsw.ef_search', ef::text, true);
        FOR q IN SELECT query_id, embedding FROM eval_queries LOOP
            -- dynamic SQL so each statement is planned with the current enable_indexscan setting
            TRUNCATE recall_a, recall_b;
            PERFORM set_config('enable_indexscan', 'on', true);
            EXECUTE 'INSERT INTO recall_a SELECT review_id FROM review_embeddings
                     ORDER BY embedding <=> $1 LIMIT 10' USING q.embedding;
            PERFORM set_config('enable_indexscan', 'off', true);
            EXECUTE 'INSERT INTO recall_b SELECT review_id FROM review_embeddings
                     ORDER BY embedding <=> $1 LIMIT 10' USING q.embedding;
            SELECT count(*) INTO n FROM recall_a JOIN recall_b USING (review_id);
            INSERT INTO recall VALUES (ef, q.query_id, n);
        END LOOP;
    END LOOP;
END $$;
SELECT ef_search, string_agg(query_id || '=' || overlap, '  ' ORDER BY query_id) AS overlap_per_query,
       round(avg(overlap) / 10, 3) AS mean_recall_at_10
FROM recall GROUP BY ef_search ORDER BY ef_search;

-- index sizes and build time
SELECT c.relname AS relation, pg_size_pretty(pg_relation_size(c.oid)) AS size
FROM pg_class c
WHERE c.relname IN ('review_embeddings', 'review_embeddings_hnsw', 'product_reviews', 'reviews_tsv_gin',
                    'reviews_details_gin', 'products_specs_gin')
ORDER BY pg_relation_size(c.oid) DESC;

\timing on
REINDEX INDEX review_embeddings_hnsw;
\timing off
