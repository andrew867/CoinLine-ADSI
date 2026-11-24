#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: restore-check.sh backup.age age-key-path" >&2
    exit 2
fi
database="restore_check_$(date -u +%Y%m%d%H%M%S)_$$"
docker compose exec -T db sh -eu -c 'createdb -U "$POSTGRES_USER" -O coinline "$1"' sh "$database"
age --decrypt -i "$2" "$1" |
    docker compose exec -T db pg_restore -U coinline -d "$database" --exit-on-error --no-owner
query='SELECT COUNT(*) AS restored_revisions FROM revisions; SELECT COUNT(*) AS restored_routes FROM routes;'
docker compose exec -T db psql -U coinline -d "$database" -v ON_ERROR_STOP=1 -c "$query"
printf 'Restored to %s.\n' "$database"
