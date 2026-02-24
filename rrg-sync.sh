#!/bin/bash
# Auto-sync rrg-server repo between machines via GitHub
# Runs on 5-minute cron on both jake-macbook and rrg-server
REPO_DIR="${RRG_REPO_DIR:-$HOME/rrg-server}"
LOG_TAG="rrg-sync"

cd "$REPO_DIR" || { echo "[$LOG_TAG] Cannot cd to $REPO_DIR" >&2; exit 1; }

# Stage all changes
git add -A

# Commit if there are staged changes
if ! git diff --cached --quiet; then
    git commit -m "auto-sync $(hostname -s) $(date +%H:%M)" --no-gpg-sign
fi

# Pull (rebase to keep history clean) then push
git pull --rebase --no-edit 2>&1
git push 2>&1
