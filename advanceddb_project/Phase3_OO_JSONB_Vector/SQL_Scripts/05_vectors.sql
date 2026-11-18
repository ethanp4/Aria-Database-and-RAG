-- Aria Phase 3 / 05: load the review embeddings and build the HNSW index.
-- Run with psql from this folder (\copy reads ../Embeddings/data/*.csv on the client).
--
-- Model     sentence-transformers/all-MiniLM-L6-v2, revision 1110a24, 384 dimensions,
--           run locally on the CPU by Embeddings/embed_reviews.py (no paid service).
-- Distance  cosine (<=>). The model is trained with a cosine objective and the vectors are
--           L2-normalised, so cosine is the natural measure (inner product would rank the same).
-- Index     HNSW with vector_cosine_ops; the opclass MUST match the operator in ORDER BY or the
--           planner cannot use the index. m = 16, ef_construction = 64 (pgvector defaults).
--
-- Embeddings are DERIVED data: product_reviews.body is authoritative, and this table can be
-- rebuilt at any time from it (Embeddings/run_pipeline.py). The model name is stored per row so
-- a future model change can coexist with / replace the old vectors safely.

CREATE TABLE review_embeddings (
    review_id   BIGINT       PRIMARY KEY,
    model       VARCHAR(100) NOT NULL DEFAULT 'sentence-transformers/all-MiniLM-L6-v2@1110a24',
    embedding   VECTOR(384)  NOT NULL,
    CONSTRAINT review_embeddings_review_fk FOREIGN KEY (review_id)
        REFERENCES product_reviews (review_id) ON DELETE CASCADE
);

-- The natural-language test questions, embedded with the same model (evaluation only).
CREATE TABLE eval_queries (
    query_id    VARCHAR(10) PRIMARY KEY,
    query_text  TEXT        NOT NULL,
    embedding   VECTOR(384) NOT NULL
);

\copy review_embeddings (review_id, embedding) FROM '../Embeddings/data/review_embeddings.csv' WITH (FORMAT csv, HEADER true)
\copy eval_queries (query_id, query_text, embedding) FROM '../Embeddings/data/query_embeddings.csv' WITH (FORMAT csv, HEADER true)

-- every review has exactly one embedding, and every vector is unit length
SELECT (SELECT count(*) FROM product_reviews)                            AS reviews,
       (SELECT count(*) FROM review_embeddings)                          AS embeddings,
       (SELECT vector_dims(embedding) FROM review_embeddings LIMIT 1)    AS dims,
       (SELECT round(min(vector_norm(embedding))::numeric, 4) FROM review_embeddings) AS min_norm,
       (SELECT round(max(vector_norm(embedding))::numeric, 4) FROM review_embeddings) AS max_norm;

\timing on
CREATE INDEX review_embeddings_hnsw ON review_embeddings
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
\timing off
VACUUM ANALYZE review_embeddings;

-- Search operation used by C1 and evaluate.py: top-k reviews nearest to a query vector.
-- The inner ORDER BY ... LIMIT is the shape the HNSW index can serve.
CREATE FUNCTION fn_search_reviews(p_query VECTOR(384), p_k INTEGER DEFAULT 5)
RETURNS TABLE (rank BIGINT, review_id BIGINT, sku VARCHAR, product_kind VARCHAR, rating SMALLINT,
               distance NUMERIC, review_text TEXT)
LANGUAGE sql STABLE AS $$
    SELECT row_number() OVER (ORDER BY top.d), top.review_id, p.sku, p.product_kind, r.rating,
           round(top.d::numeric, 4), left(r.title || '. ' || r.body, 150)
    FROM (SELECT e.review_id, e.embedding <=> p_query AS d
          FROM review_embeddings e
          ORDER BY e.embedding <=> p_query
          LIMIT p_k) AS top
    JOIN product_reviews r ON r.review_id = top.review_id
    JOIN products p ON p.product_id = r.product_id
    ORDER BY top.d
$$;

SELECT indexrelid::regclass::text AS relation, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_index WHERE indrelid = 'review_embeddings'::regclass
UNION ALL
SELECT 'review_embeddings (table + TOAST)', pg_size_pretty(pg_total_relation_size('review_embeddings')
                                            - pg_indexes_size('review_embeddings'));
