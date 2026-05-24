#!/usr/bin/env bash
# Weekly off-host backup transfer.
#
# Expected to be invoked from host cron, e.g.:
#   30 4 * * 0  /opt/interactome/deploy/rsync-offhost.sh >> /var/log/interactome/rsync.log 2>&1
#
# Env vars (set in /etc/default/interactome-rsync, sourced below):
#   RSYNC_TARGET   — e.g. backup@backup.simbiosys.sb.upf.edu:/data/interactome
#   RSYNC_SSH_KEY  — path to the SSH key, e.g. /etc/interactome/rsync.key

set -euo pipefail

if [ -f /etc/default/interactome-rsync ]; then
    # shellcheck disable=SC1091
    . /etc/default/interactome-rsync
fi

: "${RSYNC_TARGET:?RSYNC_TARGET must be set}"
: "${RSYNC_SSH_KEY:?RSYNC_SSH_KEY must be set}"

DOCKER_VOLUME_ROOT=${DOCKER_VOLUME_ROOT:-/var/lib/docker/volumes}

echo "[rsync-offhost] starting at $(date -u +%FT%TZ)"
echo "[rsync-offhost] target=$RSYNC_TARGET"

# pgbackrest repo
rsync -avz --delete --partial \
    -e "ssh -i $RSYNC_SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$DOCKER_VOLUME_ROOT/interactome_backupdata/_data/" \
    "$RSYNC_TARGET/backupdata/"

# MinIO blob storage
rsync -avz --delete --partial \
    -e "ssh -i $RSYNC_SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$DOCKER_VOLUME_ROOT/interactome_miniodata/_data/" \
    "$RSYNC_TARGET/miniodata/"

echo "[rsync-offhost] PASSED at $(date -u +%FT%TZ)"
