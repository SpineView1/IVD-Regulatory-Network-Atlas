#!/usr/bin/env bash
set -euo pipefail

# First-time stanza creation. Idempotent: pgbackrest returns 0 if stanza exists.
echo "[pgbackrest] ensuring stanza exists..."
until pg_isready -h postgres -U pgbackrest -d interactome -q; do
    echo "[pgbackrest] waiting for postgres..."
    sleep 3
done

pgbackrest --stanza=interactome --log-level-console=info stanza-create || true
pgbackrest --stanza=interactome check

# Install crontab and start cron in foreground.
crontab /etc/cron.d/pgbackrest-cron
exec cron -f -L 15
