#!/usr/bin/env bash
# Run every portfolio query against aria_phase2 and save its output (query text + results)
# to expected_output/<file>.txt. Same connection settings as SQL_Scripts/run_all.sh
# (PGHOST, PGPORT, PGUSER, PGPASSWORD or a pgpass file; PSQL if psql is not on PATH).
#
# Files run in order, so Q08-Q10 install the views, triggers and procedure that later files use.
# A few files demonstrate rejected operations on purpose; their errors are marked
# "EXPECTED ERROR" in the SQL. This script fails only on errors that are not expected.
set -uo pipefail
cd "$(dirname "$0")"
PSQL="${PSQL:-psql}"
mkdir -p expected_output

declare -A EXPECTED_ERRORS=([Q09_triggers.sql]=1 [Q11_checkout_transaction.sql]=2)
status=0
for f in Q*.sql; do
    out="expected_output/${f%.sql}.txt"
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
