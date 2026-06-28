#!/usr/bin/env bash
# CT108 host-side autodeploy for dcbot.
#
# Polls origin/main; only when there are new commits does it fast-forward,
# sync config.yaml onto the data bind, rebuild the image and restart the
# container. A failed build leaves the running container untouched (fail-safe)
# and HEAD already advanced, so it won't rebuild the same bad commit in a loop.
#
# Run by dcbot-autodeploy.timer every few minutes. Logs to $LOG.
set -euo pipefail

REPO_DIR=/root/dcbot
DATA_DIR=/mnt/docker-data/dcbot          # the runtime bind mount (config.yaml lives here at runtime)
BRANCH=main
DEPLOY_KEY=/root/.ssh/dcbot_deploy
LOG=/var/log/dcbot-autodeploy.log

exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') autodeploy check ==="

# Use the read-only deploy key for all git network ops (no reliance on ~/.ssh/config or HOME).
export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "ERROR: $REPO_DIR is not a git repo"; exit 1; }

before=$(git rev-parse HEAD)
git fetch --quiet origin "$BRANCH"
after=$(git rev-parse "origin/$BRANCH")

if [ "$before" = "$after" ]; then
  echo "no change (${before:0:8}), skip."
  exit 0
fi

echo "change: ${before:0:8} -> ${after:0:8}"
git merge --ff-only "origin/$BRANCH"

# Runtime config.yaml is read from the bind, not the image. Sync it only when
# this pull actually changed config.yaml (so we never clobber a hand-edited bind copy).
if git diff --name-only "$before" "$after" | grep -qx 'config.yaml'; then
  echo "config.yaml changed -> syncing to bind ($DATA_DIR/config.yaml)"
  cp -f config.yaml "$DATA_DIR/config.yaml"
fi

echo "building image..."
docker compose build

echo "restarting container..."
docker compose up -d

echo "deployed $(git rev-parse --short HEAD)."
