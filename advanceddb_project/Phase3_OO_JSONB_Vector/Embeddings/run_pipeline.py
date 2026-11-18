"""Aria Phase 3: regenerate everything from raw text and rerun the evaluation, in one command.

    source text  ->  clean  ->  embed (local CPU)  ->  load into PostgreSQL  ->  index  ->  evaluate

Steps (run in this order; each one's outputs are the next one's inputs)
    generate   generate_dataset.py   product specs SQL + data/reviews_raw.csv + eval/ground_truth.csv
    clean      clean_reviews.py      data/reviews_clean.csv + data_quality_report.md
    embed      embed_reviews.py      data/review_embeddings.csv + data/query_embeddings.csv
    load       psql                  SQL_Scripts/00..06 (tables, \\copy, HNSW index, integrity checks)
    queries    psql                  SQL_Scripts/A1..D1, output saved to Query_Results/ (optional)
    evaluate   evaluate.py           Query_Results/evaluation.md (precision@5)

Usage (from this folder, with the venv's Python; see ../README.md for setup)
    python run_pipeline.py --all                  # every step, including the query files
    python run_pipeline.py generate clean embed   # offline steps only, no database needed
    python run_pipeline.py load evaluate          # reload the committed CSVs and re-score

Database connection: the standard PostgreSQL environment variables PGHOST, PGPORT, PGUSER and
PGPASSWORD (or a pgpass file). The aria_phase2 database must already be built by
Phase2_Implementation/SQL_Scripts/run_all. Set PSQL if psql is not on PATH.
Nothing secret is read from or written to the repository.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQL_DIR = HERE.parent / 'SQL_Scripts'
RESULTS = HERE.parent / 'Query_Results'
SETUP_FILES = ['00_prereqs.sql', '01_hierarchy_tables.sql', '02_product_seed.sql',
               '03_hierarchy_rules_and_ops.sql', '04_reviews.sql', '05_vectors.sql', '06_verify.sql']
QUERY_FILES = ['A1_hierarchy_demo.sql', 'B1_jsonb_queries.sql', 'C1_semantic_search.sql',
               'C2_filtered_vector_search.sql', 'C3_hybrid_search.sql', 'C4_index_comparison.sql',
               'C5_scale_test.sql', 'D1_combined_query.sql']
EXPECTED_ERRORS = {'A1_hierarchy_demo.sql': 5, 'B1_jsonb_queries.sql': 2}   # deliberate rule violations
STEPS = ['generate', 'clean', 'embed', 'load', 'queries', 'evaluate']


def find_psql():
    """psql from $PSQL, then PATH, then the default Windows install folder."""
    candidates = [os.environ.get('PSQL'), shutil.which('psql'),
                  r'C:\Program Files\PostgreSQL\18\bin\psql.exe']
    for c in candidates:
        if c and Path(c).exists():
            return c
    sys.exit('psql not found: install the PostgreSQL client or set PSQL to its full path')


def run_python(script):
    # the same interpreter (the venv) runs every Python step
    subprocess.run([sys.executable, str(HERE / script)], cwd=HERE, check=True)


def run_psql_file(psql, name, stop_on_error=True):
    """Run one SQL file from SQL_Scripts (so its relative \\copy paths resolve); save the output."""
    args = [psql, '-X', '-e', '-d', os.environ.get('PGDATABASE', 'aria_phase2'), '-f', name]
    if stop_on_error:
        args[1:1] = ['-v', 'ON_ERROR_STOP=1']
    out = RESULTS / (('setup_' if name in SETUP_FILES else '') + Path(name).stem + '.txt')
    # stderr is merged into stdout so NOTICEs and errors appear next to the statement that caused them
    proc = subprocess.run(args, cwd=SQL_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace')
    out.write_text(proc.stdout, encoding='utf-8', newline='\n')
    return proc.returncode, proc.stdout.count('ERROR:'), out


def step_load():
    psql = find_psql()
    for name in SETUP_FILES:
        code, _, out = run_psql_file(psql, name)
        if code != 0:
            sys.exit(f'load failed in {name}; see {out}')
        print(f'  ok   {name}')


def step_queries():
    psql = find_psql()
    failed = False
    for name in QUERY_FILES:
        _, errors, out = run_psql_file(psql, name, stop_on_error=False)
        expected = EXPECTED_ERRORS.get(name, 0)
        status = 'ok  ' if errors == expected else 'FAIL'
        failed |= errors != expected
        print(f'  {status} {name} ({errors} errors, {expected} expected)')
    if failed:
        sys.exit('some query files had unexpected errors; see Query_Results/')


ACTIONS = {
    'generate': lambda: run_python('generate_dataset.py'),
    'clean': lambda: run_python('clean_reviews.py'),
    'embed': lambda: run_python('embed_reviews.py'),
    'load': step_load,
    'queries': step_queries,
    'evaluate': lambda: run_python('evaluate.py'),
}


def main():
    parser = argparse.ArgumentParser(description='Regenerate Phase 3 data and embeddings, load, and evaluate.')
    parser.add_argument('steps', nargs='*', help=f'steps to run, any of {STEPS} (default: all)')
    parser.add_argument('--all', action='store_true', help='run every step')
    args = parser.parse_args()
    unknown = [s for s in args.steps if s not in STEPS]
    if unknown:
        parser.error(f'unknown step(s) {unknown}; choose from {STEPS}')
    chosen = STEPS if args.all or not args.steps else [s for s in STEPS if s in args.steps]
    RESULTS.mkdir(exist_ok=True)
    os.environ.setdefault('HF_HUB_OFFLINE', '1' if (HERE / 'model_cache').exists() else '0')
    for step in chosen:
        t0 = time.perf_counter()
        print(f'== {step}')
        ACTIONS[step]()
        print(f'   {step} done in {time.perf_counter() - t0:.1f}s')


if __name__ == '__main__':
    main()
