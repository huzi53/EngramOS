#!/usr/bin/env bash
# Restore the latest restic snapshot into a scratch DB and print row counts.
# This is the "restore from backup works" half of the M0 exit test.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && source .env && set +a

RESTORE_DIR="$(mktemp -d)"
restic restore latest --target "$RESTORE_DIR"

DUMP_FILE="$(find "$RESTORE_DIR" -name 'engram-db.dump' | head -n1)"
if [ -z "$DUMP_FILE" ]; then
    echo "no engram-db.dump found in latest snapshot" >&2
    exit 1
fi

SCRATCH_DB="engram_restore_check"
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP DATABASE IF EXISTS $SCRATCH_DB;"
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE $SCRATCH_DB;"
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$SCRATCH_DB" < "$DUMP_FILE"

echo "row counts in $SCRATCH_DB:"
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$SCRATCH_DB" -c "SELECT count(*) AS users FROM users;"

rm -rf "$RESTORE_DIR"
