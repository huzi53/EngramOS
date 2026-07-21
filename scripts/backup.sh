#!/usr/bin/env bash
# Nightly Postgres backup -> restic. Run from the repo root (cron or manual).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && source .env && set +a

DUMP_FILE="$(mktemp -d)/engram-db.dump"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$DUMP_FILE"

restic backup "$DUMP_FILE"
# restic backup /data   # uncomment once M1 raw-file capture exists

restic forget --keep-daily 7 --keep-weekly 4 --prune

rm -f "$DUMP_FILE"
restic snapshots
