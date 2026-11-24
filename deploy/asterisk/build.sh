#!/bin/sh
set -eu
mods=/image/usr/lib/asterisk/modules
find "$mods" -maxdepth 1 -name '*.so' -printf '%f\n' | sed 's/\.so$//' | sort > /build/installed
diff -u /build/allowlist /build/installed
for profile in gateway reference; do
    install -d "/profiles/$profile/modules"
    cat /build/common.modules "/build/$profile.modules" | sort -u > "/profiles/$profile/allowlist"
    while IFS= read -r module; do
        install -m 755 "$mods/$module.so" "/profiles/$profile/modules/"
    done < "/profiles/$profile/allowlist"
done
