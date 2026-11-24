#!/usr/bin/env bash
set -euo pipefail

mkdir -p build
work=$(mktemp -d build/promotion.XXXXXX)
suffix=$(basename "$work" | cut -d. -f2 | tr '[:upper:]' '[:lower:]')
export COMPOSE_PROJECT_NAME="coinline-adsi-stage-$suffix"
export ADSI_DB_VOLUME="$COMPOSE_PROJECT_NAME-db"
export ADSI_ENV_FILE=.env
export COMPOSE_PATH_SEPARATOR=:
export COMPOSE_FILE="compose.yaml:$work/staging.yaml"
cat > "$work/staging.yaml" <<'YAML'
services:
  gateway:
    ports: !reset []
  app:
    ports: !reset []
  terminal-emu:
    image: coinline-adsi-terminal-emu
YAML

trap 'docker compose stop app gateway db' EXIT
namespace="127.0.0.1:1/$COMPOSE_PROJECT_NAME"

stage_local() {
    local source=$1 target=$2 digest
    docker tag "$source" "$target"
    digest=$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$target" |
        awk -F@ -v repository="${target%:*}" '$1 == repository { print $2; exit }')
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    docker image inspect "${target%:*}@$digest" >/dev/null || return 1
    printf '%s\n' "$digest"
}

ADSI_APP_DIGEST=$(stage_local coinline-adsi-app "$namespace/app:known-good")
ADSI_GATEWAY_DIGEST=$(stage_local coinline-adsi-gateway "$namespace/gateway:known-good")
export ADSI_APP_DIGEST ADSI_GATEWAY_DIGEST
sh deploy/promote.sh "$namespace"

cat > "$work/Dockerfile" <<'DOCKERFILE'
FROM coinline-adsi-gateway:latest
COPY broken.conf /etc/coinline/extensions-gateway.conf
DOCKERFILE
printf '[coinline]\nexten => 6500,1,Hangup(34)\n' > "$work/broken.conf"
broken="$COMPOSE_PROJECT_NAME-gateway"
docker build --tag "$broken" "$work"
candidate=$(stage_local "$broken" "$namespace/gateway:broken")
if ADSI_GATEWAY_DIGEST="$candidate" sh deploy/promote.sh "$namespace"; then
    echo "The failing SIP candidate was incorrectly accepted." >&2
    exit 1
fi

for service in app gateway; do
    identifier=$(docker compose ps -q "$service")
    active=$(docker inspect --format '{{.Config.Image}}' "$identifier")
    expected=$ADSI_APP_DIGEST
    if [ "$service" = gateway ]; then expected=$ADSI_GATEWAY_DIGEST; fi
    test "$active" = "$namespace/$service@$expected"
done
docker compose --profile verify run --rm -T --no-deps terminal-emu gateway lab
echo "Verified digest promotion, failed SIP canary and restoration in the isolated local staging stack."
