-- C5  Performance at scale: 100,000 review vectors (about 40x our real data)
-- At 2,390 rows an exact scan takes only a few milliseconds, so the index barely matters. Aria's
-- target is 1,000,000 transactions/month, and reviews grow with orders. This builds 100,000
-- realistic vectors (each real embedding copied ~42 times with small random noise, then
-- re-normalised, so the data is clustered like real text, not uniform noise), builds the same
-- HNSW index, and compares query time with and without it.
-- Takes about a minute (mostly the index build). Uses an UNLOGGED scratch table that is dropped
-- at the end; real data is not touched. Timings vary by machine; the shapes are the point.

SET maintenance_work_mem = '512MB';          -- lets the HNSW graph be built in memory
SET max_parallel_maintenance_workers = 0;    -- single-threaded build: comparable across machines
DROP TABLE IF EXISTS scale_vectors;
CREATE UNLOGGED TABLE scale_vectors (id INTEGER PRIMARY KEY, embedding VECTOR(384) NOT NULL);

\timing on
INSERT INTO scale_vectors
SELECT g,
       l2_normalize(b.embedding + (SELECT array_agg((random() - 0.5) * 0.15)::vector
                                   FROM generate_series(1, 384) WHERE g > 0))
FROM generate_series(1, 100000) AS g
JOIN (SELECT row_number() OVER (ORDER BY review_id) AS n, embedding FROM review_embeddings) b
  ON b.n = 1 + g % 2390;

CREATE INDEX scale_vectors_hnsw ON scale_vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
\timing off
ANALYZE scale_vectors;

SELECT count(*) AS vectors,
       pg_size_pretty(pg_table_size('scale_vectors'))         AS table_size,
       pg_size_pretty(pg_relation_size('scale_vectors_hnsw')) AS hnsw_index_size
FROM scale_vectors;

-- with the HNSW index
EXPLAIN (ANALYZE, COSTS OFF)
SELECT id FROM scale_vectors
ORDER BY embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = 'S4') LIMIT 10;

-- without it (parallel sequential scan computing 100,000 distances, then top-N sort)
SET enable_indexscan = off;
EXPLAIN (ANALYZE, COSTS OFF)
SELECT id FROM scale_vectors
ORDER BY embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = 'S4') LIMIT 10;
RESET enable_indexscan;

DROP TABLE scale_vectors;
