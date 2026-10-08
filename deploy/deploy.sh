#!/bin/bash
# Pull-based deploy: if GitHub has a newer release than the one running, deploy it.
# Run by arena-deploy.timer every 5 minutes. Nothing on GitHub can reach into the server.
set -euo pipefail

REPO=michalomegalul/bot-arena
DIR=/opt/bot-arena
cd "$DIR"

latest=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | jq -r .tag_name)
current=$(cat .deployed 2>/dev/null || true)
if [[ -z "$latest" || "$latest" == "null" || "$latest" == "$current" ]]; then
  exit 0
fi

echo "Deploying $latest (was: ${current:-nothing})"
# The compose file from the release itself, so stack changes ship with the code.
curl -fsSL "https://raw.githubusercontent.com/$REPO/$latest/deploy/compose.yml" -o compose.yml.new
mv compose.yml.new compose.yml

export ARENA_VERSION="$latest"
docker compose --profile cli pull --quiet
docker compose up -d --wait db
docker compose run --rm arena db migrate
echo "$latest" > .deployed
docker image prune -f >/dev/null
echo "Deployed $latest"
