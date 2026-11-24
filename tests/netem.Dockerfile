FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends iproute2=6.15.0-1
ENTRYPOINT ["tc"]
