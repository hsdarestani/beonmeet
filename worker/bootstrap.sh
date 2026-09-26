#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/opt/beonmeet-worker}"
cd "$ROOT"

if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git curl ca-certificates
fi

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

if [ -f prebuilt-images.tar ]; then
  echo "Loading prebuilt BeOnMeet recorder images..."
  docker load -i prebuilt-images.tar
  rm -f prebuilt-images.tar
else
  echo "Prebuilt image bundle missing; falling back to source build"
  UPSTREAM_COMMIT=1447ed3a38ce052a694872141a9b7085189e8513
  if [ ! -d upstream/.git ]; then
    rm -rf upstream
    git clone https://github.com/screenappai/meeting-bot.git upstream
  fi
  cd upstream
  git fetch --all --tags --prune
  git reset --hard "$UPSTREAM_COMMIT"
  cd ..
  cp patches/disk-uploader.ts upstream/src/middleware/disk-uploader.ts
  cp patches/Dockerfile.chrome-cdp upstream/Dockerfile.chrome-cdp
  cp patches/start-chrome-cdp.sh upstream/scripts/start-chrome-cdp.sh
  cp patches/JobStore.ts upstream/src/lib/JobStore.ts
  chmod +x upstream/scripts/start-chrome-cdp.sh
  python3 patches/apply-upstream-fixes.py
  sed -i 's/npx playwright install --with-deps$/npx playwright install --with-deps chromium/' upstream/Dockerfile.production
  sed -i 's/npx playwright install$/npx playwright install chromium/' upstream/Dockerfile.production
  sed -i 's/RUN npm run build/RUN NODE_OPTIONS=--max-old-space-size=2048 npm run build/' upstream/Dockerfile.production
  docker build -t beonmeet-meeting-bot:latest -f upstream/Dockerfile.production upstream
  docker build -t beonmeet-chrome-cdp:latest -f upstream/Dockerfile.chrome-cdp upstream
  docker build -t beonmeet-worker-agent:latest -f worker/Dockerfile .
fi

mkdir -p /dev/shm/beonmeet chrome-profile
chmod 777 /dev/shm/beonmeet
chown -R 1001:1001 chrome-profile
rm -f chrome-profile/SingletonLock chrome-profile/SingletonSocket chrome-profile/SingletonCookie || true

docker compose --env-file worker.env -f worker/docker-compose.yml up -d --no-build --remove-orphans
docker compose --env-file worker.env -f worker/docker-compose.yml ps
