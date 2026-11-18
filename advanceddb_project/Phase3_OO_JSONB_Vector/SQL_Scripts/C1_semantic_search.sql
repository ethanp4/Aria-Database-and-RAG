-- C1  Part C: six natural-language searches a user of Aria would make (top 5 each)
-- Each question was embedded with the same model as the reviews (all-MiniLM-L6-v2, 384 dims)
-- and stored in eval_queries. Results are ranked by cosine distance (<=>, smaller = closer).
-- Relevance marks and precision@5 are in Query_Results/evaluation.md (produced by
-- Embeddings/evaluate.py from the same queries).

SELECT query_id, query_text FROM eval_queries WHERE query_id LIKE 'S%' ORDER BY query_id;

-- what the index does for one search: HNSW index scan ordered by distance, no sort, no full scan
EXPLAIN (ANALYZE, COSTS OFF)
SELECT review_id
FROM review_embeddings
ORDER BY embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = 'S1')
LIMIT 5;

-- S1  Customer, before buying a mask: "my mask keeps steaming up so I can't see anything underwater"
SELECT * FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = 'S1'));

-- S2  Customer in cold water: "my wetsuit wasn't warm enough and I got really cold"
SELECT * FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = 'S2'));

-- S3  Staff answering a complaint: "regulator is hard to breathe from on deep dives"
SELECT * FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = 'S3'));

-- S4  Customer comparing computers: "dive computer battery runs out too quickly"
SELECT * FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = 'S4'));

-- S5  Travelling diver: "light gear that is easy to pack when flying to a dive trip"
SELECT * FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = 'S5'));

-- S6  Customer with sore feet: "fins that hurt my feet"
SELECT * FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = 'S6'));
