FROM debian:bookworm-slim AS build
ARG PJPROJECT_VERSION=2.16
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl libspandsp-dev libssl-dev nlohmann-json3-dev pkg-config
WORKDIR /pjproject
RUN curl -fsSLo source.tar.gz "https://codeload.github.com/pjsip/pjproject/tar.gz/refs/tags/${PJPROJECT_VERSION}" \
    && tar -xzf source.tar.gz --strip-components=1 \
    && ./configure --disable-video --disable-sound --disable-ffmpeg --disable-v4l2 \
    && make dep && make -j4 && make install
WORKDIR /terminal
COPY terminal-emu/*.cpp terminal-emu/*.hpp ./
RUN c++ -std=c++20 -O2 -Wall -Wextra -Werror main.cpp terminal.cpp -o terminal-emu \
    $(pkg-config --static --cflags --libs libpjproject spandsp)

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libspandsp2 libssl3 libstdc++6 \
    && useradd --system --uid 10003 terminal \
    && install -d -o terminal -g terminal /var/lib/terminal
COPY --from=build /terminal/terminal-emu /usr/local/bin/terminal-emu
USER terminal
ENTRYPOINT ["terminal-emu"]
