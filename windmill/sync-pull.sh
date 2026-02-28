#!/bin/bash
# Pull latest Windmill flows/scripts to local files for version control
# Runs hourly on cron; changes are auto-committed by rrg-sync.sh (every 5 min)
cd "$(dirname "$0")"
nix-shell -p nodejs_22 --run "npx windmill-cli@latest sync pull \
  --base-url http://localhost:8000 \
  --workspace rrg \
  --token "${WINDMILL_TOKEN:?WINDMILL_TOKEN env var must be set}" \
  --yes" 2>&1
