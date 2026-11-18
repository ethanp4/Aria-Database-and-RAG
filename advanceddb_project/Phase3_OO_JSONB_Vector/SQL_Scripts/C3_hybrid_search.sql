-- C3  Part C: hybrid search = full-text search + vector similarity, fused with Reciprocal Rank Fusion
-- Request (a customer planning a shore dive in West Vancouver):
--   "what did divers think of the gear they used at Whytecliff Park"
-- Exact words matter: the customer wants ONE place. To the embedding model, "Whytecliff Park",
-- "Porteau Cove" and "Ogden Point" are all "cold BC shore dive", so vector search alone mixes in
-- reviews from other sites. Full-text search matches the exact name but cannot rank by meaning.
-- Relevant = the review text mentions Whytecliff.
--
-- RRF score = sum over the two rankings of 1 / (60 + rank). k = 60 is the usual constant; it
-- rewards items that rank well in BOTH lists without having to calibrate cosine distance against
-- ts_rank scores (they are on different scales).

\set h1 '(SELECT embedding FROM eval_queries WHERE query_id = ''H1'')'

SELECT count(*) FILTER (WHERE body LIKE '%Whytecliff%') AS reviews_mentioning_whytecliff,
       count(*) AS all_reviews
FROM product_reviews;

-- 1. vector only
SELECT s.rank, s.review_id, s.sku, s.distance,
       r.body LIKE '%Whytecliff%' AS mentions_whytecliff,
       left(r.body, 110) AS body
FROM fn_search_reviews(:h1, 10) s
JOIN product_reviews r USING (review_id)
ORDER BY s.rank;

-- 2. full-text only (exact term)
SELECT row_number() OVER (ORDER BY ts_rank_cd(body_tsv, q) DESC, review_id) AS rank,
       review_id, round(ts_rank_cd(body_tsv, q)::numeric, 4) AS ts_rank,
       left(body, 110) AS body
FROM product_reviews, websearch_to_tsquery('english', 'Whytecliff') AS q
WHERE body_tsv @@ q
ORDER BY rank
LIMIT 5;

-- 3. hybrid: top 50 from each method, fused with RRF
WITH vec AS (
    SELECT review_id, row_number() OVER (ORDER BY d) AS rnk
    FROM (SELECT review_id, embedding <=> :h1 AS d
          FROM review_embeddings ORDER BY embedding <=> :h1 LIMIT 50) v
), fts AS (
    SELECT review_id, row_number() OVER (ORDER BY ts_rank_cd(body_tsv, q) DESC, review_id) AS rnk
    FROM product_reviews, websearch_to_tsquery('english', 'Whytecliff') AS q
    WHERE body_tsv @@ q
    ORDER BY rnk LIMIT 50
), fused AS (
    SELECT review_id,
           sum(1.0 / (60 + rnk))                AS rrf,
           max(rnk) FILTER (WHERE src = 'vec')  AS vector_rank,
           max(rnk) FILTER (WHERE src = 'fts')  AS text_rank
    FROM (SELECT review_id, rnk, 'vec' AS src FROM vec
          UNION ALL
          SELECT review_id, rnk, 'fts' FROM fts) s
    GROUP BY review_id
)
SELECT row_number() OVER (ORDER BY f.rrf DESC, f.review_id) AS rank,
       f.review_id, p.sku, round(f.rrf, 5) AS rrf, f.vector_rank, f.text_rank,
       r.body LIKE '%Whytecliff%' AS mentions_whytecliff,
       left(r.body, 100) AS body
FROM fused f
JOIN product_reviews r USING (review_id)
JOIN products p USING (product_id)
ORDER BY f.rrf DESC, f.review_id
LIMIT 10;

-- 4. side by side: precision@5 and @10 (relevant = mentions Whytecliff)
WITH vec_ranked AS (
    SELECT review_id, row_number() OVER (ORDER BY d) AS rnk
    FROM (SELECT review_id, embedding <=> :h1 AS d
          FROM review_embeddings ORDER BY embedding <=> :h1 LIMIT 50) v
), fts AS (
    SELECT review_id, row_number() OVER (ORDER BY ts_rank_cd(body_tsv, q) DESC, review_id) AS rnk
    FROM product_reviews, websearch_to_tsquery('english', 'Whytecliff') AS q
    WHERE body_tsv @@ q ORDER BY rnk LIMIT 50
), hybrid AS (
    SELECT review_id, row_number() OVER (ORDER BY sum(1.0 / (60 + rnk)) DESC, review_id) AS rnk
    FROM (SELECT review_id, rnk FROM vec_ranked UNION ALL SELECT review_id, rnk FROM fts) s
    GROUP BY review_id
), scored AS (
    SELECT 'vector only' AS method, v.rnk, r.body LIKE '%Whytecliff%' AS rel
    FROM vec_ranked v JOIN product_reviews r USING (review_id)
    UNION ALL
    SELECT 'hybrid (FTS + vector, RRF)', h.rnk, r.body LIKE '%Whytecliff%'
    FROM hybrid h JOIN product_reviews r USING (review_id)
)
SELECT method,
       count(*) FILTER (WHERE rel AND rnk <= 5)  || '/5'  AS "precision@5",
       count(*) FILTER (WHERE rel AND rnk <= 10) || '/10' AS "precision@10"
FROM scored
GROUP BY method
ORDER BY method DESC;
