#!/bin/sh
set -eu
# Reuse the pinned, compiled gateway source. Add only the NAT supplement needed
# to rewrite SIP Contacts through the host UDP port publication.
menuselect/menuselect --enable res_pjsip_nat menuselect.makeopts
menuselect/menuselect --check-deps menuselect.makeopts
make -j6 -o third-party NOISY_BUILD=no
make -o third-party install DESTDIR=/image
mods=/image/usr/lib/asterisk/modules
{ cat /build/allowlist; echo res_pjsip_nat; } | sort -u > /build/emu-allowlist
find "$mods" -maxdepth 1 -name '*.so' -printf '%f\n' | sed 's/\.so$//' | sort > /build/emu-installed
diff -u /build/emu-allowlist /build/emu-installed
install -d /profiles/emu/modules
{ cat /profiles/gateway/allowlist; echo res_pjsip_nat; } | sort -u > /profiles/emu/allowlist
while IFS= read -r module; do
    install -m 755 "$mods/$module.so" /profiles/emu/modules/
done < /profiles/emu/allowlist
