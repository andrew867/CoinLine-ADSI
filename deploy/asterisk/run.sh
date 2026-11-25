#!/bin/sh
set -eu
profile=$1
config=/run/asterisk
umask 077

check_secret() {
    case "$1" in
        ''|*[!A-Fa-f0-9]*) return 1 ;;
    esac
    test "${#1}" -ge 32
}

check_secret "${ADSI_SIP_PASSWORD:-}" || { echo "Set a hex lab SIP password of at least 32 characters." >&2; exit 1; }
for file in asterisk.conf rtp.conf logger.conf cdr.conf cel.conf manager.conf; do
    cp "/etc/coinline/$file" "$config/$file"
done
sed "s/@SIP_PASSWORD@/$ADSI_SIP_PASSWORD/g" /etc/coinline/pjsip.conf > "$config/pjsip.conf"
if [ "$profile" = native ]; then
    case "${ADSI_NATIVE_MAIL_PIN:-}" in
        ''|*[!0-9]*) echo "Set an eight-digit native mailbox PIN." >&2; exit 1 ;;
    esac
    test "${#ADSI_NATIVE_MAIL_PIN}" -eq 8 || { echo "Set an eight-digit native mailbox PIN." >&2; exit 1; }
    cp /etc/coinline/extensions-gateway.conf "$config/extensions.conf"
    cat /etc/coinline/extensions-native.conf >> "$config/extensions.conf"
    sed "s/@MAIL_PIN@/$ADSI_NATIVE_MAIL_PIN/g" /etc/coinline/voicemail-native.conf > "$config/voicemail.conf"
else
    cp "/etc/coinline/extensions-$profile.conf" "$config/extensions.conf"
fi
if [ "${ADSI_EMU_ENABLE:-0}" = 1 ]; then
    test "$profile" = gateway || { echo "Emulator ingress requires the gateway profile." >&2; exit 1; }
    caller=${ADSI_EMU_CALLER_ID:-7095550100}
    printf '%s\n' "$caller" | grep -Eq '^[2-9][0-9]{2}[2-9][0-9]{6}$' || {
        echo "Set a ten-digit synthetic emulator caller ID." >&2; exit 1;
    }
    self_ip=$(hostname -i | awk '{print $1}')
    printf '%s\n' "$self_ip" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || {
        echo "The emulator ingress requires an IPv4 gateway address." >&2; exit 1;
    }
    printf '\n' >> "$config/pjsip.conf"
    sed "s/@EMU_CONTAINER_IP@/$self_ip/g;s/@EMU_CALLER_ID@/$caller/g" /etc/coinline/pjsip-emu.conf >> "$config/pjsip.conf"
    cat /etc/coinline/extensions-emu.conf >> "$config/extensions.conf"
    cp /etc/coinline/rtp-emu.conf "$config/rtp.conf"
fi
{
    echo '[modules]'
    echo 'autoload=no'
    while IFS= read -r module; do
        printf 'require => %s.so\n' "$module"
    done < /opt/coinline/modules
} > "$config/modules.conf"
if [ "$profile" = gateway ] || [ "$profile" = native ]; then
    check_secret "${ADSI_ARI_PASSWORD:-}" || { echo "Set a hex ARI password of at least 32 characters." >&2; exit 1; }
    cp /etc/coinline/http.conf "$config/http.conf"
    sed "s/@ARI_PASSWORD@/$ADSI_ARI_PASSWORD/g" /etc/coinline/ari.conf > "$config/ari.conf"
    sed "s/@ARI_PASSWORD@/$ADSI_ARI_PASSWORD/g" /etc/coinline/websocket_client.conf > "$config/websocket_client.conf"
fi
exec asterisk -f -C "$config/asterisk.conf"
