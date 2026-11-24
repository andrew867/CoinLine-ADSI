#!/usr/bin/env bash
set -euo pipefail
namespace="ghcr.io/$(printf '%s' "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')"
[[ "$GITHUB_REF_NAME" =~ ^v[0-9][a-zA-Z0-9._-]*$ ]]
printf '%s' "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
docker compose --profile verify build reference terminal-emu
docker buildx create --name coinline-release --driver docker-container
mkdir -p build/release

build_candidate() {
    local component=$1 dockerfile=$2
    shift 2
    local -a flags=(
        --builder coinline-release --push --provenance=mode=max --sbom=true
        --label "org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY"
        --label "org.opencontainers.image.revision=$GITHUB_SHA"
        --tag "$namespace/$component:candidate-$GITHUB_SHA"
        --metadata-file "build/release/$component.json" --file "$dockerfile"
    )
    docker buildx build "${flags[@]}" "$@" .
}

build_candidate app service/Dockerfile
build_candidate gateway deploy/asterisk/Dockerfile --target gateway
app_digest=$(jq -er '."containerimage.digest"' build/release/app.json)
gateway_digest=$(jq -er '."containerimage.digest"' build/release/gateway.json)
export ADSI_APP_IMAGE="$namespace/app@$app_digest"
export ADSI_GATEWAY_IMAGE="$namespace/gateway@$gateway_digest"
docker pull "$ADSI_APP_IMAGE"
docker pull "$ADSI_GATEWAY_IMAGE"
docker compose --profile verify up -d --no-build --wait gateway app reference
sh tests/check-modules.sh
sh tests/smoke.sh
python tests/check_admission.py
python tests/live_dtmf.py
python tests/live_api.py
python tests/live_sip_app.py
python tests/live_balance_demo.py
python tests/load_lab.py
python tests/live_capacity.py

for component in app gateway; do
    digest=$(jq -er '."containerimage.digest"' "build/release/$component.json")
    docker buildx imagetools create --tag "$namespace/$component:$GITHUB_REF_NAME" "$namespace/$component@$digest"
done
jq -n --arg app "$app_digest" --arg gateway "$gateway_digest" --arg commit "$GITHUB_SHA" '{app:$app,gateway:$gateway,commit:$commit}' > build/release/coinline-release.json
gh release create "$GITHUB_REF_NAME" --verify-tag --generate-notes build/release/coinline-release.json
