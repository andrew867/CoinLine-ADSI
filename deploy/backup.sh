#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: backup.sh output.age age-recipient" >&2
    exit 2
fi
output=$1
umask 077
if [ -e "$output" ] || [ -e "$output.pending" ]; then
    echo "Choose a new backup path." >&2
    exit 1
fi
docker compose exec -T db pg_dump -U coinline -d coinline --format=custom --no-owner |
    age -r "$2" -o "$output.pending"
mv "$output.pending" "$output"
