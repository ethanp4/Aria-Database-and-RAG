"""Aria Phase 3, pipeline step 3: embed every clean review and every evaluation query.

Model   sentence-transformers/all-MiniLM-L6-v2 (pinned revision in model_config.py), 384 dimensions,
        run locally on the CPU with sentence-transformers. Free and open (Apache-2.0).
Reads   data/reviews_clean.csv, eval/queries.csv
Writes  data/review_embeddings.csv   review_id, embedding   (pgvector text format '[x,y,...]')
        data/query_embeddings.csv    query_id, query_text, embedding

Vectors are L2-normalised, so cosine distance (pgvector's <=> operator) ranks them the same way
as the inner product would, and each value is written with 7 decimal places.

Long reviews: text over the model's 254 content tokens is split into overlapping token windows.
Each window is embedded and the window vectors are averaged and normalised again, so the
whole review is represented instead of only the first 254 tokens.
"""
import csv
import time
from pathlib import Path

import numpy as np

import model_config as mc

HERE = Path(__file__).resolve().parent
CLEAN = HERE / 'data' / 'reviews_clean.csv'
QUERIES = HERE / 'eval' / 'queries.csv'
OUT_REVIEWS = HERE / 'data' / 'review_embeddings.csv'
OUT_QUERIES = HERE / 'data' / 'query_embeddings.csv'


def windows(token_ids, tokenizer):
    """Split a token list into overlapping windows and decode each one back to text."""
    out = []
    for start in range(0, len(token_ids), mc.WINDOW_STRIDE):
        chunk = token_ids[start:start + mc.CONTENT_TOKENS]
        out.append(tokenizer.decode(chunk))
        if start + mc.CONTENT_TOKENS >= len(token_ids):
            break
    return out


def vector_literal(vec):
    return '[' + ','.join(f'{x:.7f}' for x in vec) + ']'


def main():
    t0 = time.perf_counter()
    model = mc.load_model()
    tokenizer = mc.load_tokenizer()
    with CLEAN.open(encoding='utf-8', newline='') as f:
        reviews = list(csv.DictReader(f))

    # Build one flat list of passages; remember which review each passage belongs to.
    passages, owner, n_windowed = [], [], 0
    for i, r in enumerate(reviews):
        text = mc.embed_text(r['title'], r['body'])
        ids = tokenizer(text, add_special_tokens=False)['input_ids']
        parts = [text] if len(ids) <= mc.CONTENT_TOKENS else windows(ids, tokenizer)
        n_windowed += len(parts) > 1
        passages.extend(parts)
        owner.extend([i] * len(parts))

    t1 = time.perf_counter()
    vectors = model.encode(passages, batch_size=64, normalize_embeddings=True, convert_to_numpy=True,
                           show_progress_bar=False)
    t2 = time.perf_counter()

    # mean-pool the windows of each review, then normalise again
    sums = np.zeros((len(reviews), mc.DIMENSIONS), dtype=np.float64)
    np.add.at(sums, np.array(owner), vectors.astype(np.float64))
    sums /= np.linalg.norm(sums, axis=1, keepdims=True)

    with OUT_REVIEWS.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['review_id', 'embedding'])
        for r, v in zip(reviews, sums):
            w.writerow([r['review_id'], vector_literal(v)])

    with QUERIES.open(encoding='utf-8', newline='') as f:
        queries = list(csv.DictReader(f))
    qvec = model.encode([q['query_text'] for q in queries], normalize_embeddings=True, convert_to_numpy=True)
    with OUT_QUERIES.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['query_id', 'query_text', 'embedding'])
        for q, v in zip(queries, qvec):
            w.writerow([q['query_id'], q['query_text'], vector_literal(v)])

    print(f'model {mc.MODEL_NAME}@{mc.MODEL_REVISION[:7]} ({mc.DIMENSIONS} dims, CPU)')
    print(f'{len(reviews)} reviews -> {len(passages)} passages ({n_windowed} long reviews embedded in windows)')
    print(f'{len(queries)} evaluation queries embedded')
    print(f'model load {t1 - t0:.1f}s, encode {t2 - t1:.1f}s ({len(passages) / (t2 - t1):.0f} passages/s)')


if __name__ == '__main__':
    main()
