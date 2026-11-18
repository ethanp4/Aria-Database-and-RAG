"""Aria Phase 3, pipeline step 5: run the evaluation searches and score precision@5.

Runs every query in eval/queries.csv against PostgreSQL (the same SQL as the SQL_Scripts/C*/D1
files), marks each top-5 result relevant / not relevant, and writes
    ../Query_Results/evaluation.md    tables per search + the precision@5 summary
    ../Query_Results/evaluation.csv   one row per (search, rank) for the report

How relevance is decided (written down before looking at results)
    Every review was generated from labelled topic sentences, and the labels are kept OUT of the
    database in eval/ground_truth.csv (e.g. review 1167 = "fogging:neg"). A result is RELEVANT when:
      * it has the search's topic with the polarity the user asked about (a complaint search wants
        complaints: "battery runs out too quickly" is not answered by "battery lasts a week"), and
      * it is about the product type the user asked about (S2 asks about wetsuits, so a glove
        review about cold fingers is not relevant).
    H1 is an exact-term search: relevant when the review text names the place.
    We also report a looser "topic only" score (right topic, either polarity, any product type)
    because it shows what the embedding model gets right and where it fails (sentiment).
    The marks were then spot-checked by reading the review text (all results of S4, S5 and F1);
    the Why column shows the label behind every mark so anyone can re-check them.

Connection: standard libpq environment variables (PGHOST, PGPORT, PGUSER, PGPASSWORD or a
pgpass file, PGDATABASE defaults to aria_phase2). Nothing is hard-coded.
"""
import csv
import os
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / 'Query_Results'
QUERIES = HERE / 'eval' / 'queries.csv'
TRUTH = HERE / 'eval' / 'ground_truth.csv'
K = 5

SQL_VECTOR = """
    SELECT s.rank, s.review_id, s.sku, s.distance, r.body
    FROM fn_search_reviews((SELECT embedding FROM eval_queries WHERE query_id = %(q)s), %(k)s) s
    JOIN product_reviews r USING (review_id) ORDER BY s.rank"""

# C2: vector + relational (product_kind) + JSONB (dive_context.water_temp_c) filter
SQL_FILTERED = """
    SELECT row_number() OVER (ORDER BY e.embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s)) AS rank, r.review_id, p.sku,
           round((e.embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s))::numeric, 4) AS distance, r.body
    FROM review_embeddings e JOIN product_reviews r USING (review_id) JOIN products p USING (product_id)
    WHERE p.product_kind = 'LIFE_SUPPORT'
      AND r.details @? '$.dive_context.water_temp_c ? (@ <= 8)'
    ORDER BY e.embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s) LIMIT %(k)s"""

# C3: reciprocal rank fusion of full-text and vector rankings
SQL_HYBRID = """
    WITH vec AS (
        SELECT review_id, row_number() OVER (ORDER BY d) AS rnk
        FROM (SELECT review_id, embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s) AS d
              FROM review_embeddings
              ORDER BY embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s) LIMIT 50) v
    ), fts AS (
        SELECT review_id, row_number() OVER (ORDER BY ts_rank_cd(body_tsv, tq) DESC, review_id) AS rnk
        FROM product_reviews, websearch_to_tsquery('english', %(term)s) AS tq
        WHERE body_tsv @@ tq ORDER BY rnk LIMIT 50
    ), fused AS (
        SELECT review_id, sum(1.0 / (60 + rnk)) AS rrf
        FROM (SELECT * FROM vec UNION ALL SELECT * FROM fts) s GROUP BY review_id
    )
    SELECT row_number() OVER (ORDER BY f.rrf DESC, f.review_id) AS rank, f.review_id, p.sku,
           round(f.rrf, 5) AS distance, r.body
    FROM fused f JOIN product_reviews r USING (review_id) JOIN products p USING (product_id)
    ORDER BY f.rrf DESC, f.review_id LIMIT %(k)s"""

# D1: vector + class hierarchy (subclass + subclass-only attribute) + JSONB containment
SQL_COMBINED = """
    SELECT row_number() OVER (ORDER BY e.embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s)) AS rank, r.review_id, v.sku,
           round((e.embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s))::numeric, 4) AS distance, r.body
    FROM review_embeddings e JOIN product_reviews r ON r.review_id = e.review_id
    JOIN v_product_catalogue v ON v.product_id = r.product_id
    WHERE v.product_kind = 'ELECTRONICS' AND v.warranty_months >= 24
      AND v.specs @> '{"features": {"nitrox": true}}'
    ORDER BY e.embedding <=> (SELECT embedding FROM eval_queries WHERE query_id = %(q)s) LIMIT %(k)s"""


def load_truth():
    truth = {}
    with TRUTH.open(encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            topics = dict(t.split(':') for t in row['topics'].split('|')) if row['topics'] else {}
            truth[int(row['review_id'])] = (row['product_type'], topics)
    return truth


def judge(query, review_id, body, truth):
    """Returns (strict_relevant, topic_relevant, note)."""
    if query['relevant_topic'].startswith('term:'):
        term = query['relevant_topic'][5:]
        hit = term in body
        return hit, hit, f'mentions {term}' if hit else f'does not mention {term}'
    ptype, topics = truth[review_id]
    topic, want = query['relevant_topic'], query['polarity']
    types = query['relevant_types'].split('|')
    has_topic = topic in topics
    polarity_ok = has_topic and (want == 'any' or topics[topic] == want)
    type_ok = types == ['*'] or ptype in types
    strict = polarity_ok and type_ok
    if strict:
        note = f'{ptype}: {topic} ({topics[topic]})'
    elif not has_topic:
        found = ', '.join(f'{t} ({p})' for t, p in topics.items()) or 'no topic sentences'
        note = f'{ptype}: off-topic [{found}]'
    elif not polarity_ok:
        note = f'{ptype}: right topic, opposite sentiment ({topics[topic]})'
    else:
        note = f'{ptype}: right topic, wrong product type'
    return strict, has_topic, note


def run(conn, query):
    qid = query['query_id']
    params = {'q': qid, 'k': K}
    if qid.startswith('F'):
        sql = SQL_FILTERED
    elif qid.startswith('D'):
        sql = SQL_COMBINED
    else:
        sql = SQL_VECTOR
    with conn.cursor() as cur:
        cur.execute("SET hnsw.iterative_scan = relaxed_order")   # filtered searches always fill LIMIT
        cur.execute(sql, params)
        rows = cur.fetchall()
        hybrid = None
        if query['relevant_topic'].startswith('term:'):
            cur.execute(SQL_HYBRID, dict(params, term=query['relevant_topic'][5:]))
            hybrid = cur.fetchall()
    return rows, hybrid


def main():
    truth = load_truth()
    with QUERIES.open(encoding='utf-8', newline='') as f:
        queries = list(csv.DictReader(f))
    dsn = '' if os.environ.get('PGDATABASE') else 'dbname=aria_phase2'
    summary, detail_rows, sections = [], [], []
    with psycopg.connect(dsn) as conn:
        for q in queries:
            rows, hybrid = run(conn, q)
            variants = [('vector only' if hybrid else q['purpose'], rows)]
            if hybrid:
                variants.append(('hybrid: full-text + vector (RRF)', hybrid))
            for label, result in variants:
                strict_hits = topic_hits = 0
                table = ['| Rank | Review | SKU | Distance / score | Review text (start) | Relevant? | Why |',
                         '|---:|---:|---|---:|---|---|---|']
                for rank, review_id, sku, dist, body in result:
                    strict, topical, note = judge(q, review_id, body, truth)
                    strict_hits += strict
                    topic_hits += topical
                    snippet = body[:90].replace('|', '/') + ('...' if len(body) > 90 else '')
                    table.append(f'| {rank} | {review_id} | {sku} | {dist} | {snippet} | '
                                 f'{"relevant" if strict else "not relevant"} | {note} |')
                    detail_rows.append([q['query_id'], label, rank, review_id, sku, dist,
                                        'relevant' if strict else 'not relevant', note])
                n = len(result)
                summary.append((q['query_id'], q['query_text'], label, strict_hits, topic_hits, n))
                sections += [f'### {q["query_id"]}: "{q["query_text"]}" ({label})', '',
                             f'precision@5 = {strict_hits}/{n} = {strict_hits / K:.2f}  '
                             f'(topic only: {topic_hits}/{n})', ''] + table + ['']

    semantic = [s for s in summary if s[0].startswith('S')]
    mean = sum(s[3] for s in semantic) / (K * len(semantic))
    mean_topic = sum(s[4] for s in semantic) / (K * len(semantic))
    lines = ['# Search evaluation (precision@5)', '',
             'Generated by `Embeddings/evaluate.py` against `aria_phase2` (HNSW index, '
             '`hnsw.ef_search` = 40, `hnsw.iterative_scan` = relaxed_order).', '',
             '**Relevant** means: right topic, the sentiment the user asked about, and the product type '
             'they asked about. **Topic only** counts any result on the right topic. The labels come from '
             '`eval/ground_truth.csv`, which is never loaded into the database. Marks were spot-checked by '
             'reading the reviews (all of S4, S5 and F1); the Why column shows the label behind each mark.', '',
             '| Search | Question | Method | precision@5 | topic only |', '|---|---|---|---:|---:|']
    for qid, text, label, hits, topical, n in summary:
        lines.append(f'| {qid} | {text} | {label} | {hits}/5 = {hits / K:.2f} | {topical}/5 |')
    lines += [f'| **S1-S6** | **mean of the six semantic searches** | | **{mean:.2f}** | **{mean_topic:.2f}** |',
              '', '## Results per search', ''] + sections
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / 'evaluation.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    with (OUT_DIR / 'evaluation.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['query_id', 'method', 'rank', 'review_id', 'sku', 'distance_or_score', 'judgement', 'why'])
        w.writerows(detail_rows)
    for qid, text, label, hits, topical, n in summary:
        print(f'{qid:3} p@5={hits}/5 topic={topical}/5  {label}')
    print(f'mean precision@5 (S1-S6) = {mean:.2f}; topic-only = {mean_topic:.2f}')


if __name__ == '__main__':
    main()
