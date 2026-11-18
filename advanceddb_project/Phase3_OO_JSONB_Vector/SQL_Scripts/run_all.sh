#!/usr/bin/env bash
# Build the Phase 3 objects on top of aria_phase2 and run every Phase 3 query file.
# Prerequisite: Phase 2 is built (Phase2_Implementation/SQL_Scripts/run_all.sh) and pgvector is
# installed on the server. Embedding CSVs must exist in ../Embeddings/data (they are committed;
# regenerate with ../Embeddings/run_pipeline.py).
#
# Usage (Git Bash / macOS / Linux):
#   export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres
#   export PGPASSWORD=...        # or use a pgpass file; never commit it
#   ./run_all.sh
# Set PSQL to the psql binary if it is not on PATH, e.g.
#   export PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"
#
# Output of every file (statements + results) is saved to ../Query_Results/<file>.txt.
# A1 and B1 contain deliberate rule violations marked "EXPECTED ERROR"; any other error fails.
set -uo pipefail
cd "$(dirname "$0")"
PSQL="${PSQL:-psql}"
OUT=../Query_Results
mkdir -p "$OUT"

for f in 00_prereqs.sql 01_hierarchy_tables.sql 02_product_seed.sql 03_hierarchy_rules_and_ops.sql \
         04_reviews.sql 05_vectors.sql 06_verify.sql; do
    echo "== $f"
    if ! "$PSQL" -X -e -v ON_ERROR_STOP=1 -d aria_phase2 -f "$f" > "$OUT/setup_${f%.sql}.txt" 2>&1; then
        echo "FAIL $f, see $OUT/setup_${f%.sql}.txt"
        tail -5 "$OUT/setup_${f%.sql}.txt"
        exit 1
    fi
done

declare -A EXPECTED_ERRORS=([A1_hierarchy_demo.sql]=5 [B1_jsonb_queries.sql]=2)
status=0
for f in A1_*.sql B1_*.sql C1_*.sql C2_*.sql C3_*.sql C4_*.sql C5_*.sql D1_*.sql; do
    out="$OUT/${f%.sql}.txt"
    "$PSQL" -X -e -d aria_phase2 -f "$f" > "$out" 2>&1
    errors=$(grep -c 'ERROR:' "$out" || true)
    expected=${EXPECTED_ERRORS[$f]:-0}
    if [ "$errors" -ne "$expected" ]; then
        echo "FAIL $f: $errors errors (expected $expected), see $out"
        status=1
    else
        echo "ok   $f"
    fi
done
exit $status
