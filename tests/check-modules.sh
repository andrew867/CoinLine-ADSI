#!/bin/sh
set -eu
for service in gateway reference; do
    docker compose --profile verify exec -T "$service" sh -eu -c '
        for module in /usr/lib/asterisk/modules/*.so; do
            printf "%s\n" "${module##*/}"
        done | sed "s/\.so$//" | sort > /run/asterisk/files
        cmp /opt/coinline/modules /run/asterisk/files
        asterisk -C /run/asterisk/asterisk.conf -rx "module show" |
            awk '"'"'$1 ~ /\.so$/ && /Running/ && !/Not Running/ { sub(/\.so$/, "", $1); print $1 }'"'"' |
            sort > /run/asterisk/loaded
        cmp /opt/coinline/modules /run/asterisk/loaded
    '
done
