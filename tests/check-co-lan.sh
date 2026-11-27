#!/bin/sh
set -eu
container=${1:?Supply the dedicated gateway container name}
docker exec "$container" sh -eu -c '
    for m in res_pjsip_nat res_pjsip_endpoint_identifier_ip app_directory app_voicemail format_wav res_adsi; do
        grep -qx "$m" /opt/coinline/modules
    done
    for module in /usr/lib/asterisk/modules/*.so; do
        printf "%s\n" "${module##*/}"
    done | sed "s/\.so$//" | sort > /run/asterisk/files
    cmp /opt/coinline/modules /run/asterisk/files
    asterisk -C /run/asterisk/asterisk.conf -rx "module show" |
        awk '\''$1 ~ /\.so$/ && /Running/ && !/Not Running/ { sub(/\.so$/, "", $1); print $1 }'\'' |
        sort > /run/asterisk/loaded
    cmp /opt/coinline/modules /run/asterisk/loaded
    asterisk -C /run/asterisk/asterisk.conf -rx "dialplan show coinline-co-lan" | grep -q "9 extensions"
    asterisk -C /run/asterisk/asterisk.conf -rx "pjsip show endpoint co" | grep -q "coinline-co-lan"
    asterisk -C /run/asterisk/asterisk.conf -rx "pjsip show identify co-lan-identify" | grep -q "co-lan-identify"
    test -f /var/lib/asterisk/sounds/en/vm-password.wav
'
