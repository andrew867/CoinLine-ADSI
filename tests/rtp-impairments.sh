#!/bin/sh
set -eu

mkdir -p build
evidence=$(mktemp -d build/rtp-faults.XXXXXX)
docker build --tag coinline-adsi-test-netem --file tests/netem.Dockerfile .
reference=$(docker compose --profile verify ps -q reference)
test -n "$reference"

control() {
    docker run --rm --read-only --network "container:$reference" --cap-drop ALL --cap-add NET_ADMIN coinline-adsi-test-netem "$@"
}

control qdisc show dev eth0 | grep -q 'qdisc noqueue 0: root'
control qdisc add dev eth0 root handle 1: prio bands 2 priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
trap 'control qdisc del dev eth0 root' EXIT
control qdisc add dev eth0 parent 1:2 handle 20: netem delay 22ms 10ms distribution normal seed 202
filter() {
    operation=$1
    shift
    control filter "$operation" dev eth0 protocol ip parent 1: prio 10 flower skip_hw ip_proto udp src_port 18000-18039 classid 1:2 "$@"
}

filter add
docker compose --profile verify run --rm -T --no-deps terminal-emu reference reference > "$evidence/jitter.jsonl"
# CAS occupies the first five packets, then the connect precedes the display.
# The 25th packet of this reference exchange contains display spill data.
control filter del dev eth0 protocol ip parent 1: prio 10
filter add action gact pass random determ drop 25
docker compose --profile verify run --rm -T --no-deps terminal-emu reference reference > "$evidence/drop.jsonl" || true
control -s -j filter show dev eth0 parent 1: > "$evidence/queue.json"
python tests/compare_calls.py "$evidence" --impairments
