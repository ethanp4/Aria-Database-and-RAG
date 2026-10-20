#!/usr/bin/env bash
# Rebuild aria_phase2 from scratch: database, tables, indexes, seed data, portfolio objects.
# Usage (Git Bash / macOS / Linux):
#   export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres
#   export PGPASSWORD=...        # or use a pgpass file; never commit it
#   ./run_all.sh
# Set PSQL to the psql binary if it is not on PATH, e.g.
#   export PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"
set -euo pipefail
cd "$(dirname "$0")"
PSQL="${PSQL:-psql}"
run() { "$PSQL" -X -q -v ON_ERROR_STOP=1 "$@"; }

run -d postgres -f 00_create_database.sql
for f in 01_tables.sql 02_indexes.sql 03_seed.sql 04_verify_seed.sql; do
    echo "== $f"
    run -d aria_phase2 -f "$f"
done
# views, functions, procedures and triggers used by the query portfolio
run -d aria_phase2 -f ../Query_Portfolio/00_portfolio_objects.sql
echo "aria_phase2 is ready."
