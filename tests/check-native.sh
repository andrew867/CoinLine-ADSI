#!/bin/sh
set -eu
docker compose -f compose.yaml -f compose.native.yaml exec -T gateway sh -eu -c '
    asterisk -C /run/asterisk/asterisk.conf -rx "core show application VoiceMailMain" | grep -q VoiceMailMain
    asterisk -C /run/asterisk/asterisk.conf -rx "core show application Directory" | grep -q Directory
    asterisk -C /run/asterisk/asterisk.conf -rx "dialplan show 6506@coinline" | grep -q Directory
    asterisk -C /run/asterisk/asterisk.conf -rx "dialplan show 6505@coinline" | grep -q VoiceMailMain
    test -f /var/lib/asterisk/sounds/en/vm-password.wav
    for m in app_directory app_voicemail format_wav res_adsi; do
        grep -qx "$m" /opt/coinline/modules
    done
    asterisk -C /run/asterisk/asterisk.conf -rx "module show" |
        awk '\''$1 ~ /\.so$/ && /Running/ && !/Not Running/ { sub(/\.so$/, "", $1); print $1 }'\'' | sort > /run/asterisk/loaded
    cmp /opt/coinline/modules /run/asterisk/loaded
'
