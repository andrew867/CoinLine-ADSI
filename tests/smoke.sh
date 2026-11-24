#!/bin/sh
set -eu
mkdir -p build
evidence=$(mktemp -d build/sip-smoke.XXXXXX)
dial() {
    if docker compose --profile verify run --rm -T --no-deps terminal-emu "$1" "$2" > "$evidence/$2.jsonl"; then
        return 0
    fi
    cat "$evidence/$2.jsonl"
    return 1
}
dial gateway lab
dial gateway fallback
dial reference reference
python tests/compare_calls.py "$evidence"
