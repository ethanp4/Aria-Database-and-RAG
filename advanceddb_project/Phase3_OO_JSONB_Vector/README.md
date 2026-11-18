# Aria Phase 3: OO hierarchy, JSONB and vector search

Phase 3 adds three things to the Phase 2 database (`aria_phase2`), in place:
1. An object-oriented **product hierarchy**: an abstract `Product` with four subclasses, mapped with class table inheritance.
2. **JSONB** for product specs and review details, whose attributes vary from item to item.
3. **Semantic search** with pgvector over 2,390 customer reviews.

One query (Part D) combines all three. **All data is synthetic.**

## What is in each folder

| Folder | Contents |
|---|---|
| `Design_Plan/` | `Design_Plan.docx` (1-2 pages): the hierarchy and mapping choice, JSONB vs relational, the model, distance and index, and where the authoritative copy of each piece of data lives. `design_plan.md` is its source. |
| `Diagrams/` | `uml_class.png` (UML class diagram) and `pipeline.png` (data pipeline, showing where JSONB enters). The `.mmd` files are the Mermaid sources. |
| `SQL_Scripts/` | `00`–`06`: setup (tables, rules, load, indexes, checks). `A1`–`D1`: the demo and evaluation queries. `run_all.sh` / `run_all.ps1` run everything. |
| `Embeddings/` | Python scripts for the data generator, cleaning, embedding, evaluation and the one-command pipeline. Also `requirements.txt`, the data CSVs (`data/`), the test questions and hidden relevance labels (`eval/`), and `data_quality_report.md`. |
| `Query_Results/` | The captured output of every SQL file (statements and results, including the EXPLAIN plans), plus `evaluation.md` and `evaluation.csv` (precision@5). |
| `Technical_Report/` | `Aria_Phase3_Technical_Report.docx`. `technical_report.md` is its source. `build_report.py` rebuilds both Word files and fills in every number from `Query_Results/`. |

| SQL file | Shows |
|---|---|
| `A1_hierarchy_demo.sql` | inheritance, polymorphism (`v_product_catalogue`, `fn_care_due_date`), encapsulation (the `aria_catalogue_app` role), and rules the database rejects |
| `B1_jsonb_queries.sql` | `@>`, `@?` / `jsonb_path_query`, `jsonb_to_recordset` joined to `products`, `jsonb_set`, CHECK violations, and the EXPLAIN of the containment query |
| `C1_semantic_search.sql` | six natural-language searches, top 5 each |
| `C2_filtered_vector_search.sql` | vector search combined with relational and JSONB filters, with EXPLAIN and row counts, and the iterative-scan fix |
| `C3_hybrid_search.sql` | full-text + vector (RRF) compared with vector only |
| `C4_index_comparison.sql` | HNSW vs exact top 10 (overlap), recall at different `ef_search` values, index sizes, build time |
| `C5_scale_test.sql` | the same comparison at 100,000 vectors |
| `D1_combined_query.sql` | Part D: vector similarity + a hierarchy condition + a JSONB condition |

## Requirements

- **PostgreSQL 18 with pgvector 0.8 or later.** We used PostgreSQL 18.6 with pgvector 0.8.7. Ways to get pgvector:
  - The EDB Windows installer for PostgreSQL 18 includes it (`share/extension/vector.control`); you can also add it with Stack Builder.
  - Linux: `apt install postgresql-18-pgvector`.
  - Docker: the image `pgvector/pgvector:pg18`.
- **`psql`**, the PostgreSQL client.
- **Python 3.10+.** Needed only to regenerate the data or embeddings, re-run the scoring, or rebuild the report. The SQL scripts load the committed CSVs and do not need Python.

## Supplying the database password

Never put a password, key or connection string in any file in this repo. Use either of these:
- **An environment variable.** It lasts only for the current terminal:
  ```bash
  export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres
  read -s -p "Postgres password: " PGPASSWORD; export PGPASSWORD
  ```
  ```powershell
  $env:PGHOST='127.0.0.1'; $env:PGPORT='5432'; $env:PGUSER='postgres'
  $env:PGPASSWORD = Read-Host 'Postgres password'
  ```
- **A pgpass file** in your home folder, outside the repo:
  - Windows: `%APPDATA%\postgresql\pgpass.conf`
  - macOS/Linux: `~/.pgpass`, with `chmod 600`

  The file holds one line: `127.0.0.1:5432:*:postgres:<password>`.

Every script reads only the standard `PG*` variables. If `psql` is not on your PATH, set `PSQL` to its full path, for example `export PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"`.

## Setup and run (in this order)

1. **Build Phase 2** (this creates `aria_phase2`):
   ```bash
   ../Phase2_Implementation/SQL_Scripts/run_all.sh        # or run_all.ps1
   ```
2. **Build Phase 3 and run every query.** `00_prereqs.sql` runs `CREATE EXTENSION vector` and stops with a clear message if Phase 2 is missing.
   ```bash
   SQL_Scripts/run_all.sh                                  # or SQL_Scripts/run_all.ps1
   ```
   - Each file's output is written to `Query_Results/`.
   - The setup files stop on the first error.
   - `A1` and `B1` contain **7 deliberate rule violations** (5 in A1, 2 in B1), each labelled `EXPECTED ERROR`. The runner checks that exactly these occur.
   - Phase 3 can be re-run: `00_prereqs.sql` removes the previous Phase 3 objects first.

## Regenerating the data and embeddings (bonus: one command)

```bash
python -m venv .venv
.venv/Scripts/pip install -r Embeddings/requirements.txt    # macOS/Linux: .venv/bin/pip
.venv/Scripts/python Embeddings/run_pipeline.py --all
```

`run_pipeline.py` runs these steps in order. You can name single steps, for example `run_pipeline.py load evaluate`.

| Step | What it does | Output |
|---|---|---|
| `generate` | `generate_dataset.py` (seed 202603): product subclasses and specs, raw reviews, hidden topic labels | `SQL_Scripts/02_product_seed.sql`, `data/reviews_raw.csv`, `eval/ground_truth.csv` |
| `clean` | `clean_reviews.py`: decodes HTML entities, normalises whitespace, drops empty bodies and duplicates, flags short and over-long texts | `data/reviews_clean.csv`, `data_quality_report.md` |
| `embed` | `embed_reviews.py`: embeds the reviews and test questions on the local CPU | `data/review_embeddings.csv`, `data/query_embeddings.csv` |
| `load` | SQL files `00`–`06` | the tables, the `\copy` loads, the HNSW and GIN indexes, integrity checks |
| `queries` | SQL files `A1`–`D1` | `Query_Results/*.txt` |
| `evaluate` | `evaluate.py`: scores precision@5 against the hidden labels | `Query_Results/evaluation.md` / `.csv` |

Then run `.venv/Scripts/python Technical_Report/build_report.py` to rebuild the two Word documents with the new numbers.

- **Model:**
  - `sentence-transformers/all-MiniLM-L6-v2`, pinned to Hugging Face revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions, licence Apache-2.0.
  - It runs on the CPU and needs no API key or paid service.
  - The first run downloads about 90 MB into `Embeddings/model_cache/`, which git ignores. Later runs work offline.
- **Install note:** for a smaller CPU-only PyTorch, install torch first from `https://download.pytorch.org/whl/cpu` (see the comment in `requirements.txt`).
- **Reproducible:**
  - The generator, cleaning and embeddings are deterministic. Rerunning them reproduced every committed CSV byte-for-byte.
  - `python Embeddings/generate_dataset.py --check` checks that the committed data still matches the generator.
  - The query timings differ between machines.

## Dataset

| | |
|---|---|
| Source | Synthetic. Generated by our own script `Embeddings/generate_dataset.py`, which was written with the help of Claude Code. It reuses the Phase 2 simulation of customers and orders (`Phase2_Implementation/SQL_Scripts/generate_seed.py`). The review text is built from per-topic paraphrase banks. No real people, reviews or scraped text. |
| Licence | Released with this repository; no third-party licence applies. |
| Size | 2,440 raw reviews → **2,390 clean reviews** for all 200 products, written by 200 customers. 648 are verified purchases linked to delivered orders. There are 2,390 embeddings of 384 dimensions. |
| Files | `reviews_raw.csv` 0.9 MB, `reviews_clean.csv` 0.9 MB, `review_embeddings.csv` 9.3 MB. All are under GitHub's 100 MB limit, so no Git LFS is needed. |
| Quality | See `Embeddings/data_quality_report.md`: what was removed, fixed and flagged, and the length compared with the model's 256-token limit. |

## Dependencies

All Python dependencies are pinned in `Embeddings/requirements.txt`, each with the reason it is needed.

| Package | Used for |
|---|---|
| torch, sentence-transformers, transformers | running the embedding model and tokenizer |
| numpy | the window averaging for long texts |
| psycopg[binary] | `evaluate.py` talks to PostgreSQL |
| python-docx | building the Word documents |

The data generator and the cleaning step use only the Python standard library.

The diagrams were rendered with `@mermaid-js/mermaid-cli` 11.4.2: `mmdc -i uml_class.mmd -o uml_class.png -s 2`. The rendered PNGs are committed, so you don't need it.
