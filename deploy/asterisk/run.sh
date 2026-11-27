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
if [ "$profile" = native ] || [ "$profile" = co-lan ]; then
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
if [ "$profile" = co-lan ]; then
    test "${ADSI_CO_LAN_ENABLE:-0}" = 1 || { echo "LAN lab must be explicitly enabled." >&2; exit 1; }
    for module in res_pjsip_nat res_pjsip_endpoint_identifier_ip app_voicemail app_directory res_adsi; do
        grep -qx "$module" /opt/coinline/modules || { echo "LAN lab module unavailable." >&2; exit 1; }
    done
    private_ipv4() {
        case "$1" in ''|*[!0-9.]*) return 1 ;; esac
        printf '%s\n' "$1" | awk -F . '
            NF != 4 {exit 1}
            {for (i=1;i<=4;i++) if ($i !~ /^[0-9]+$/ || length($i)>3 || $i>255) exit 1}
            {if ($1==10 || ($1==172 && $2>=16 && $2<=31) || ($1==192 && $2==168)) exit 0; exit 1}'
    }
    host=${ADSI_CO_LAN_BIND:-}
    peer=${ADSI_CO_LAN_PEER:-}
    private_ipv4 "$host" && private_ipv4 "$peer" || {
        echo "LAN lab requires exact private IPv4 bind and peer addresses." >&2; exit 1;
    }
    caller=${ADSI_CO_LAN_CALLER_ID:-7095550100}
    printf '%s\n' "$caller" | grep -Eq '^[2-9][0-9]{2}[2-9][0-9]{6}$' || {
        echo "Set a ten-digit synthetic LAN caller ID." >&2; exit 1;
    }
    self_ip=$(hostname -i | awk '{print $1}')
    printf '%s\n' "$self_ip" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || exit 1
    sed -i 's/^endpoint_identifier_order=.*/endpoint_identifier_order=ip,username,auth_username/' "$config/pjsip.conf"
    printf '\n' >> "$config/pjsip.conf"
    sed "s/@CONTAINER_IP@/$self_ip/g;s/@HOST_IP@/$host/g;s/@PEER_IP@/$peer/g;s/@CALLER_ID@/$caller/g" \
        /etc/coinline/pjsip-co-lan.conf >> "$config/pjsip.conf"
    cat /etc/coinline/extensions-co-lan.conf >> "$config/extensions.conf"
    cp /etc/coinline/rtp-co-lan.conf "$config/rtp.conf"
fi
if [ "${ADSI_EMU_ENABLE:-0}" = 1 ]; then
    test "$profile" = gateway || { echo "Emulator ingress requires the gateway profile." >&2; exit 1; }
    grep -qx res_pjsip_nat /opt/coinline/modules || {
        echo "Emulator ingress requires the dedicated NAT-capable gateway image." >&2; exit 1;
    }
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
if [ "$profile" = gateway ] || [ "$profile" = native ] || [ "$profile" = co-lan ]; then
    check_secret "${ADSI_ARI_PASSWORD:-}" || { echo "Set a hex ARI password of at least 32 characters." >&2; exit 1; }
    cp /etc/coinline/http.conf "$config/http.conf"
    sed "s/@ARI_PASSWORD@/$ADSI_ARI_PASSWORD/g" /etc/coinline/ari.conf > "$config/ari.conf"
    sed "s/@ARI_PASSWORD@/$ADSI_ARI_PASSWORD/g" /etc/coinline/websocket_client.conf > "$config/websocket_client.conf"
fi
exec asterisk -f -C "$config/asterisk.conf"
