#!/bin/sh
set -eu
# The separate LAN laboratory needs native mailbox apps and exact IP identification.
test -f /profiles/native/allowlist
menuselect/menuselect --enable res_pjsip_nat --enable res_pjsip_endpoint_identifier_ip menuselect.makeopts
menuselect/menuselect --check-deps menuselect.makeopts
make -j6 -o third-party NOISY_BUILD=no
make -o third-party install DESTDIR=/image
mods=/image/usr/lib/asterisk/modules
{
    cat /build/allowlist
    printf '%s\n' res_pjsip_nat res_pjsip_endpoint_identifier_ip
} | sort -u > /build/co-lan-allowlist
find "$mods" -maxdepth 1 -name '*.so' -printf '%f\n' | sed 's/\.so$//' | sort > /build/co-lan-installed
diff -u /build/co-lan-allowlist /build/co-lan-installed
install -d /profiles/co-lan/modules
{
    cat /profiles/native/allowlist
    printf '%s\n' res_pjsip_nat res_pjsip_endpoint_identifier_ip
} | sort -u > /profiles/co-lan/allowlist
while IFS= read -r module; do
    install -m 755 "$mods/$module.so" /profiles/co-lan/modules/
done < /profiles/co-lan/allowlist
