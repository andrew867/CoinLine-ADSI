#!/bin/sh
set -eu
make menuselect.makeopts
cat /build/*.modules | sort -u > /build/allowlist
set -- --disable-all
for module in $(cat /build/allowlist); do
    set -- "$@" --enable "$module"
done
menuselect/menuselect "$@" menuselect.makeopts
menuselect/menuselect --check-deps menuselect.makeopts
