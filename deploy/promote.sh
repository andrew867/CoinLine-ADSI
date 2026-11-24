#!/bin/sh
set -eu
printf '%s\n' "$ADSI_APP_DIGEST" | grep -Eq '^sha256:[0-9a-f]{64}$'
printf '%s\n' "$ADSI_GATEWAY_DIGEST" | grep -Eq '^sha256:[0-9a-f]{64}$'
test -f "${ADSI_ENV_FILE:?Set the deployment environment file}"
previous_app=$(docker compose --env-file "$ADSI_ENV_FILE" ps -q app)
previous_gateway=$(docker compose --env-file "$ADSI_ENV_FILE" ps -q gateway)
if [ -n "$previous_app" ] && [ -n "$previous_gateway" ]; then
    previous_app=$(docker inspect --format '{{.Config.Image}}' "$previous_app")
    previous_gateway=$(docker inspect --format '{{.Config.Image}}' "$previous_gateway")
fi
export ADSI_APP_IMAGE="$1/app@$ADSI_APP_DIGEST"
export ADSI_GATEWAY_IMAGE="$1/gateway@$ADSI_GATEWAY_DIGEST"
for image in "$ADSI_APP_IMAGE" "$ADSI_GATEWAY_IMAGE"; do
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        docker pull "$image"
    fi
done
if docker compose --env-file "$ADSI_ENV_FILE" up -d --no-build --force-recreate --wait app gateway &&
   docker compose --env-file "$ADSI_ENV_FILE" --profile verify run --rm -T --no-deps terminal-emu gateway lab; then
    exit 0
fi
if [ -n "$previous_app" ] && [ -n "$previous_gateway" ]; then
    export ADSI_APP_IMAGE="$previous_app" ADSI_GATEWAY_IMAGE="$previous_gateway"
    docker compose --env-file "$ADSI_ENV_FILE" up -d --no-build --force-recreate --wait app gateway
    docker compose --env-file "$ADSI_ENV_FILE" --profile verify run --rm -T --no-deps terminal-emu gateway lab
fi
exit 1
