"""Aria Phase 3, pipeline step 2: review data quality audit + cleaning.

Reads  data/reviews_raw.csv            (written by generate_dataset.py)
Writes data/reviews_clean.csv          (what 04_reviews.sql loads into product_reviews)
       data_quality_report.md          (the data review: counts, lengths, problems, decisions)

Cleaning rules, in order
    1. Decode HTML entities left by the old web form (&amp; -> &, &#39; -> ').
    2. Normalise whitespace: collapse runs of spaces / tabs / line breaks to one space, trim.
    3. Drop reviews whose body is empty after trimming (nothing to embed or search).
    4. Remove duplicates. Two rows are duplicates when the same account reviewed the same product
       with the same text after case-folding and whitespace normalisation. The earliest review_id
       is kept (the later ones are double submits / re-submits). Exact and near duplicates are
       counted separately in the report.
    5. Keep very short bodies (< 15 characters, e.g. "Great.") but flag them in the report: they
       are genuine ratings, but carry little meaning for semantic search.
    6. Count how many embedded texts exceed the model's 256-token input window, using the model's
       own tokenizer. Those rows are not cut; embed_reviews.py embeds them in overlapping windows.
"""
import csv
import html
import json
import re
import statistics
from collections import Counter
from pathlib import Path

import model_config as mc

HERE = Path(__file__).resolve().parent
RAW = HERE / 'data' / 'reviews_raw.csv'
CLEAN = HERE / 'data' / 'reviews_clean.csv'
REPORT = HERE / 'data_quality_report.md'
SHORT_CHARS = 15
WS = re.compile(r'\s+')


def normalise(text):
    return WS.sub(' ', html.unescape(text)).strip()


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def describe(values):
    return (f'min {min(values)}, median {statistics.median(values):g}, p90 {pct(values, 0.9)}, '
            f'p99 {pct(values, 0.99)}, max {max(values)}, mean {statistics.mean(values):.1f}')


def main():
    with RAW.open(encoding='utf-8', newline='') as f:
        raw = list(csv.DictReader(f))
    header = list(raw[0].keys())

    issues = Counter()
    issue_ids = {k: [] for k in ('html_entities', 'whitespace', 'empty', 'exact_duplicate',
                                 'near_duplicate', 'very_short', 'over_token_limit')}
    seen = {}               # (account, product, folded body) -> kept review_id
    seen_raw = {}           # (account, product, raw body) -> kept review_id
    clean = []
    for row in sorted(raw, key=lambda r: int(r['review_id'])):
        body_raw = row['body']
        if html.unescape(body_raw) != body_raw or html.unescape(row['title']) != row['title']:
            issue_ids['html_entities'].append(row['review_id'])
        body = normalise(body_raw)
        if body != html.unescape(body_raw):
            issue_ids['whitespace'].append(row['review_id'])
        if not body:
            issue_ids['empty'].append(row['review_id'])
            continue
        key = (row['account_id'], row['product_id'], body.casefold())
        if key in seen:
            raw_key = (row['account_id'], row['product_id'], body_raw)
            kind = 'exact_duplicate' if raw_key in seen_raw else 'near_duplicate'
            issue_ids[kind].append(f"{row['review_id']} (copy of {seen[key]})")
            continue
        seen[key] = row['review_id']
        seen_raw[(row['account_id'], row['product_id'], body_raw)] = row['review_id']
        json.loads(row['details'])                          # must be valid JSON
        clean.append(dict(row, title=normalise(row['title']), body=body))

    # token lengths measured with the model's own tokenizer (no special tokens)
    tokenizer = mc.load_tokenizer()
    texts = [mc.embed_text(r['title'], r['body']) for r in clean]
    token_lens = [len(ids) for ids in tokenizer(texts, add_special_tokens=False)['input_ids']]
    for r, n in zip(clean, token_lens):
        if len(r['body']) < SHORT_CHARS:
            issue_ids['very_short'].append(r['review_id'])
        if n > mc.CONTENT_TOKENS:
            issue_ids['over_token_limit'].append(r['review_id'])

    with CLEAN.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator='\n')
        w.writeheader()
        w.writerows(clean)

    # ---------------------------------------------------------------- report
    chars = [len(r['body']) for r in clean]
    words = [len(r['body'].split()) for r in clean]
    ratings = Counter(int(r['rating']) for r in clean)
    verified = sum(1 for r in clean if r['order_id'])
    with_context = sum(1 for r in clean if 'dive_context' in json.loads(r['details']))
    products = len({r['product_id'] for r in clean})
    accounts = len({r['account_id'] for r in clean})
    removed = len(raw) - len(clean)
    lines = [
        '# Review data quality report',
        '',
        'Generated by `clean_reviews.py` from `data/reviews_raw.csv`. All data is synthetic.',
        '',
        '## Summary',
        '',
        '| Measure | Value |',
        '|---|---:|',
        f'| Raw rows | {len(raw):,} |',
        f'| Removed: empty body | {len(issue_ids["empty"])} |',
        f'| Removed: exact duplicates (same account, product and text) | {len(issue_ids["exact_duplicate"])} |',
        f'| Removed: near duplicates (differ only in case/spacing) | {len(issue_ids["near_duplicate"])} |',
        f'| **Clean rows loaded into `product_reviews`** | **{len(clean):,}** |',
        f'| Fixed in place: HTML entities decoded | {len(issue_ids["html_entities"])} |',
        f'| Fixed in place: whitespace / line breaks normalised | {len(issue_ids["whitespace"])} |',
        f'| Kept but flagged: very short body (< {SHORT_CHARS} chars) | {len(issue_ids["very_short"])} |',
        f'| Kept, embedded in windows: over {mc.CONTENT_TOKENS} tokens | {len(issue_ids["over_token_limit"])} |',
        f'| Products with at least one review | {products} of 200 |',
        f'| Distinct reviewers | {accounts} |',
        f'| Verified purchases (`order_id` set) | {verified:,} ({verified / len(clean):.0%}) |',
        f'| Reviews with a `dive_context` object in `details` | {with_context:,} ({with_context / len(clean):.0%}) |',
        f'| Rating distribution 5/4/3/2/1 | {"/".join(str(ratings[k]) for k in (5, 4, 3, 2, 1))} |',
        '',
        '## Length of the clean text',
        '',
        f'- Body characters: {describe(chars)}',
        f'- Body words: {describe(words)}',
        f'- Embedded text (`title. body`) in model tokens: {describe(token_lens)}',
        f'- Model input limit: {mc.MAX_SEQ_TOKENS} tokens including [CLS]/[SEP], so {mc.CONTENT_TOKENS} '
        'tokens of text. Anything longer would be silently cut off by the model.',
        '',
        '## Decisions',
        '',
        '- **Empty bodies are dropped.** The title alone is a generic phrase like "Average"; there is nothing',
        '  to search.',
        '- **Duplicates keep the earliest `review_id`.** The copies come from double submits (seconds apart)',
        '  and re-submits (hours later, retyped). `UNIQUE (account_id, product_id)` on `product_reviews`',
        '  stops new ones at the database level.',
        '- **Very short bodies are kept.** The rating is real and useful for averages. Their embeddings',
        '  carry little meaning, so they rarely surface in semantic search, which is the right behaviour.',
        f'- **Over-long texts are not truncated.** `embed_reviews.py` splits them into {mc.CONTENT_TOKENS}-token',
        f'  windows that start every {mc.WINDOW_STRIDE} tokens, embeds each window, and averages the',
        '  normalised vectors, so the end of a long review still counts.',
        '- **Keys.** `product_id`, `account_id` and `order_id` are BIGINT keys from `aria_phase2`. The',
        '  foreign keys and the verified-purchase trigger check them again when the CSV is loaded.',
        '',
        '## Row ids per issue',
        '',
    ]
    for k, ids in issue_ids.items():
        shown = ', '.join(ids[:40]) + (' ...' if len(ids) > 40 else '')
        lines.append(f'- `{k}` ({len(ids)}): {shown or "none"}')
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(f'raw {len(raw)} -> clean {len(clean)} (removed {removed}); '
          f'over-limit {len(issue_ids["over_token_limit"])}; short {len(issue_ids["very_short"])}')


if __name__ == '__main__':
    main()
