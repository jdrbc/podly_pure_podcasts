#!/bin/bash

set -euo pipefail

# Branch name becomes part of a manual tag (slashes replaced)
BRANCH=$(git rev-parse --abbrev-ref HEAD | tr '/' '_')

# Allow overriding image/owner/builder via env vars
IMAGE=${IMAGE:-ghcr.io/jdrbc/podly-pure-podcasts}
BUILDER=${BUILDER:-podly_builder}

# Ensure a docker-container buildx builder for multi-arch builds
docker buildx create --name "${BUILDER}" --driver docker-container --use >/dev/null 2>&1 || docker buildx use "${BUILDER}"

# Ensure binfmt handlers for cross-compilation are installed (no-op if already present)
docker run --privileged --rm tonistiigi/binfmt --install all >/dev/null 2>&1 || true

# Optional GHCR login (requires GHCR_TOKEN and optionally OWNER)
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  OWNER=${OWNER:-$(echo "${IMAGE}" | sed -E 's#^ghcr.io/([^/]+)/.*$#\1#')}
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${OWNER}" --password-stdin
fi

# Build and push multi-arch CPU image (lite)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${IMAGE}:${BRANCH}-lite" \
  --build-arg BASE_IMAGE=python:3.11-slim \
  --build-arg USE_GPU=false \
  --build-arg USE_GPU_NVIDIA=false \
  --build-arg USE_GPU_AMD=false \
  --build-arg LITE_BUILD=true \
  --push .
