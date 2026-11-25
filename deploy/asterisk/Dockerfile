FROM debian:bookworm-slim AS source
ARG ASTERISK_VERSION=22.12.0
ARG ASTERISK_SHA256=f8b2ba98aac6c4ff3376bc0a2868bea6ed577ca684efb7ec739ae6e8ce6e35e2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl pkg-config python3 libedit-dev libjansson-dev \
    libsqlite3-dev libssl-dev libxml2-dev libncurses-dev uuid-dev
WORKDIR /src
RUN curl -fsSLo asterisk.tar.gz "https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-${ASTERISK_VERSION}.tar.gz" \
    && printf '%s  %s\n' "$ASTERISK_SHA256" asterisk.tar.gz | sha256sum -c \
    && tar xzf asterisk.tar.gz --strip-components=1
RUN ./configure --with-pjproject-bundled --without-dahdi --without-pri --without-binutils
COPY deploy/asterisk/*.modules /build/
COPY deploy/asterisk/native.modules.opt /build/
COPY deploy/asterisk/app_coinline_reference.c apps/
COPY --chmod=755 deploy/asterisk/select-modules.sh /build/
ARG ADSI_NATIVE_MAIL=0
RUN if [ "$ADSI_NATIVE_MAIL" = 1 ]; then cp /build/native.modules.opt /build/native.modules; fi \
    && /build/select-modules.sh && menuselect/menuselect --enable OPTIONAL_API menuselect.makeopts \
    && if [ "$ADSI_NATIVE_MAIL" = 1 ]; then menuselect/menuselect --enable CORE-SOUNDS-EN-WAV menuselect.makeopts; fi
RUN make -j1 third-party
RUN make -j6 -o third-party NOISY_BUILD=no && make -o third-party install DESTDIR=/image
COPY --chmod=755 deploy/asterisk/build.sh /build/
RUN /build/build.sh

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libedit2 libjansson4 libsqlite3-0 libssl3 libxml2 libuuid1 \
    && useradd --system --uid 10001 --home-dir /var/lib/asterisk asterisk \
    && install -d -o asterisk -g asterisk /run/asterisk /var/log/asterisk /var/spool/asterisk /var/lib/asterisk
COPY --chmod=755 deploy/asterisk/run.sh /usr/local/bin/coinline-asterisk
COPY deploy/asterisk/config/ /etc/coinline/
ENTRYPOINT ["/usr/local/bin/coinline-asterisk"]
HEALTHCHECK --interval=5s --timeout=3s --start-period=12s CMD ["asterisk", "-C", "/run/asterisk/asterisk.conf", "-rx", "core show uptime"]
COPY --from=source /image/usr/lib/libasterisk*.so.* /usr/lib/

FROM runtime AS gateway
COPY --from=source /image/usr/sbin/asterisk /usr/sbin/
COPY --from=source /profiles/gateway/modules/ /usr/lib/asterisk/modules/
COPY --from=source /profiles/gateway/allowlist /opt/coinline/modules
COPY --chown=asterisk:asterisk --from=source /image/var/lib/asterisk/ /var/lib/asterisk/
USER asterisk
CMD ["gateway"]

FROM runtime AS reference
COPY --from=source /image/usr/sbin/asterisk /usr/sbin/
COPY --from=source /profiles/reference/modules/ /usr/lib/asterisk/modules/
COPY --from=source /profiles/reference/allowlist /opt/coinline/modules
COPY --chown=asterisk:asterisk --from=source /image/var/lib/asterisk/ /var/lib/asterisk/
USER asterisk
CMD ["reference"]

FROM runtime AS gateway-native
COPY --from=source /image/usr/sbin/asterisk /usr/sbin/
COPY --from=source /profiles/native/modules/ /usr/lib/asterisk/modules/
COPY --from=source /profiles/native/allowlist /opt/coinline/modules
COPY --chown=asterisk:asterisk --from=source /image/var/lib/asterisk/ /var/lib/asterisk/
USER asterisk
CMD ["native"]
